"""print_agent.py — Local desktop print agent.

A GUI window, run on the intake PC, that:
  1. Lists that PC's installed printers (local + network) and lets you
     pick one — this is the piece that has to run locally, since the
     Heroku-hosted Streamlit app's server process has no access to any
     desktop's hardware (same reason serial_console.py only reaches
     real serial ports when run locally, not when deployed).
  2. In **Live Mode**, polls the broker (slack-to-onedrive-sync's
     /print-jobs endpoints) on an interval, and for each pending job
     renders + prints the label, then acks it. This is how a real scan
     in the Camera Asset Intake workflow ends up on paper — no manual
     typing needed once this is running.
  3. Manual fields further down still work too, for testing the
     printer/rendering path (e.g. against "Microsoft Print to PDF")
     without needing the broker or a real scan.

Test against "Microsoft Print to PDF" (pick it from the printer
dropdown) — it will pop its own Windows "Save Print Output As" dialog
per job; that's the driver's own behavior, not a bug here.

Run: pip install -r requirements.txt && python print_agent.py
"""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from PIL import ImageTk

import agent_config
import broker
import label
import printing


class PrintAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Camera Label — Print Agent")
        root.geometry("560x820")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._preview_image = None  # keep a reference so Tk doesn't GC it
        self._live_polling = False
        self._poll_after_id = None
        self._config = agent_config.load()

        self._build_printer_section()
        self._build_live_mode_section()
        self._build_label_fields()
        self._build_actions()
        self._build_preview()
        self._build_log()

        self._log("Ready.")
        self.refresh_printers()

    # ── Printer selection ────────────────────────────────────────────────
    def _build_printer_section(self):
        frame = ttk.LabelFrame(self.root, text="Printer (this PC)")
        frame.pack(fill="x", padx=12, pady=(12, 6))

        self.printer_var = tk.StringVar()
        self.printer_combo = ttk.Combobox(frame, textvariable=self.printer_var, state="readonly", width=48)
        self.printer_combo.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        ttk.Button(frame, text="Refresh", command=self.refresh_printers).grid(row=0, column=1, padx=8, pady=8)

    def refresh_printers(self):
        try:
            printers = printing.list_printers()
        except Exception as exc:
            messagebox.showerror("Printer list failed", str(exc))
            return
        self.printer_combo["values"] = printers
        default = printing.default_printer()
        if default in printers:
            self.printer_var.set(default)
        elif printers:
            self.printer_var.set(printers[0])
        self._log(f"Found {len(printers)} printer(s): {', '.join(printers) or '(none)'}")

    # ── Live Mode (poll the broker) ──────────────────────────────────────
    def _build_live_mode_section(self):
        frame = ttk.LabelFrame(self.root, text="Live Mode (poll broker for real scans)")
        frame.pack(fill="x", padx=12, pady=6)

        ttk.Label(frame, text="Broker URL", width=14).grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self.broker_url_var = tk.StringVar(value=self._config["broker_url"])
        ttk.Entry(frame, textvariable=self.broker_url_var, width=38).grid(row=0, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(frame, text="Device Token", width=14).grid(row=1, column=0, padx=8, pady=4, sticky="w")
        self.device_token_var = tk.StringVar(value=self._config["device_token"])
        self.device_token_entry = ttk.Entry(frame, textvariable=self.device_token_var, width=32, show="•")
        self.device_token_entry.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        self.show_token_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame, text="show", variable=self.show_token_var,
            command=lambda: self.device_token_entry.configure(show="" if self.show_token_var.get() else "•"),
        ).grid(row=1, column=2, padx=(0, 8), pady=4, sticky="w")

        ttk.Label(frame, text="Poll every (sec)", width=14).grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.poll_interval_var = tk.IntVar(value=self._config["poll_interval_seconds"])
        ttk.Spinbox(frame, from_=2, to=60, textvariable=self.poll_interval_var, width=6).grid(
            row=2, column=1, padx=8, pady=4, sticky="w"
        )

        self.live_status_var = tk.StringVar(value="Stopped")
        ttk.Label(frame, textvariable=self.live_status_var).grid(row=3, column=0, padx=8, pady=(4, 8), sticky="w")
        self.live_toggle_btn = ttk.Button(frame, text="▶ Start", command=self.toggle_live_mode)
        self.live_toggle_btn.grid(row=3, column=1, padx=8, pady=(4, 8), sticky="w")

    def toggle_live_mode(self):
        if self._live_polling:
            self._live_polling = False
            if self._poll_after_id is not None:
                self.root.after_cancel(self._poll_after_id)
                self._poll_after_id = None
            self.live_toggle_btn.configure(text="▶ Start")
            self.live_status_var.set("Stopped")
            self._log("Live Mode stopped.")
            return

        broker_url = self.broker_url_var.get().strip()
        device_token = self.device_token_var.get().strip()
        if not broker_url or not device_token:
            messagebox.showwarning("Missing config", "Broker URL and Device Token are both required.")
            return
        if not self.printer_var.get():
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return

        agent_config.save({
            "broker_url": broker_url,
            "device_token": device_token,
            "poll_interval_seconds": self.poll_interval_var.get(),
        })

        self._live_polling = True
        self.live_toggle_btn.configure(text="⏹ Stop")
        self._log(f"Live Mode started — polling {broker_url} every {self.poll_interval_var.get()}s.")
        # Fingerprint only (length + last 4 chars) — enough to compare against
        # what's actually stored in the broker's Heroku config vars without
        # ever logging the real secret. A length mismatch usually means
        # trailing whitespace got pasted into the Heroku config var itself.
        self._log(f"Using device token: {len(device_token)} chars, ending '...{device_token[-4:]}'")
        self._poll_once()

    def _poll_once(self):
        if not self._live_polling:
            return

        broker_url = self.broker_url_var.get().strip()
        device_token = self.device_token_var.get().strip()
        printer = self.printer_var.get()

        try:
            jobs = broker.list_pending(broker_url, device_token)
        except Exception as exc:
            self.live_status_var.set(f"Error (retrying): {exc}")
            self._log(f"⚠️ Poll failed: {exc}")
            jobs = []
        else:
            self.live_status_var.set(f"Polling — last check {datetime.now().strftime('%H:%M:%S')}, {len(jobs)} pending")

        for job in jobs:
            self._print_job(broker_url, device_token, printer, job)

        if self._live_polling:
            self._poll_after_id = self.root.after(self.poll_interval_var.get() * 1000, self._poll_once)

    def _print_job(self, broker_url: str, device_token: str, printer: str, job: dict):
        data = label.LabelData(
            camera_number=job.get("camera_number") or "—",
            serial_number=job.get("serial_number") or "",
            model_number=job.get("model_number") or "",
            site_name=job.get("site_name") or "",
            loc_code=job.get("loc_code") or "",
        )
        try:
            img = label.render_label(data)
            printing.print_image(printer, img, job_name=f"Camera Label {data.camera_number}")
        except Exception as exc:
            self._log(f"❌ Print failed for job {job.get('job_id')}: {exc}")
            return  # leave it pending — will retry next poll

        try:
            broker.ack(broker_url, device_token, job["job_id"])
        except Exception as exc:
            self._log(f"⚠️ Printed {data.camera_number} but ack failed (may reprint next poll): {exc}")
            return

        self._log(f"🖨️ Printed + acked: {data.camera_number} / {data.serial_number}")

    def _on_close(self):
        self._live_polling = False
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
        self.root.destroy()

    # ── Label fields (manual test input) ────────────────────────────────
    def _build_label_fields(self):
        frame = ttk.LabelFrame(self.root, text="Label fields (manual test input)")
        frame.pack(fill="x", padx=12, pady=6)

        self.fields: dict[str, tk.StringVar] = {}
        rows = [
            ("camera_number", "Camera Number", "CAM06"),
            ("serial_number", "Serial Number", "B8A44F9C9745"),
            ("model_number", "Model Number", "P3827-PVE"),
            ("site_name", "Site Name", "Will Rogers Continuation High"),
            ("loc_code", "Loc Code", "8895"),
        ]
        for i, (key, label_text, default) in enumerate(rows):
            ttk.Label(frame, text=label_text, width=16).grid(row=i, column=0, padx=8, pady=4, sticky="w")
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=36).grid(row=i, column=1, padx=8, pady=4, sticky="w")
            self.fields[key] = var

    def _current_label_data(self) -> label.LabelData:
        return label.LabelData(
            camera_number=self.fields["camera_number"].get().strip(),
            serial_number=self.fields["serial_number"].get().strip(),
            model_number=self.fields["model_number"].get().strip(),
            site_name=self.fields["site_name"].get().strip(),
            loc_code=self.fields["loc_code"].get().strip(),
        )

    # ── Actions ───────────────────────────────────────────────────────────
    def _build_actions(self):
        frame = ttk.Frame(self.root)
        frame.pack(fill="x", padx=12, pady=6)
        ttk.Button(frame, text="🔍 Preview", command=self.preview).pack(side="left", padx=4)
        ttk.Button(frame, text="🖨️ Print", command=self.print_now).pack(side="left", padx=4)

    def preview(self):
        img = label.render_label(self._current_label_data())
        thumb = img.copy()
        thumb.thumbnail((480, 240))
        self._preview_image = ImageTk.PhotoImage(thumb)
        self.preview_label.configure(image=self._preview_image)
        self._log("Preview updated.")

    def print_now(self):
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return
        img = label.render_label(self._current_label_data())
        try:
            printing.print_image(printer, img, job_name="Camera Label")
        except Exception as exc:
            self._log(f"❌ Print failed: {exc}")
            messagebox.showerror("Print failed", str(exc))
            return
        self._log(f"✅ Sent to '{printer}'.")
        if printer == "Microsoft Print to PDF":
            self._log("  → Windows should now prompt a 'Save Print Output As' dialog.")

    # ── Preview + log widgets ────────────────────────────────────────────
    def _build_preview(self):
        frame = ttk.LabelFrame(self.root, text="Preview")
        frame.pack(fill="x", padx=12, pady=6)
        self.preview_label = ttk.Label(frame)
        self.preview_label.pack(padx=8, pady=8)

    def _build_log(self):
        frame = ttk.LabelFrame(self.root, text="Log")
        frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self.log_text = tk.Text(frame, height=8, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    PrintAgentApp(root)
    root.mainloop()
