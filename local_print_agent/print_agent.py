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
from tkinter import simpledialog, ttk, messagebox

from PIL import ImageTk

import agent_config
import broker
import label
import printing
import templates


class PrintAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Camera Label — Print Agent")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Six stacked sections (Printer, Live Mode, Label fields, Actions,
        # Preview, Log) add up to ~820px tall — taller than the usable work
        # area on plenty of laptop screens (1366x768 minus taskbar is
        # ~728px) once you account for Windows scaling. Fixed-size +
        # non-resizable used to just crop whatever didn't fit, with no way
        # to reach it. Scrollable content + a resizable window fixes that
        # on any screen: everything is reachable via scroll/resize/maximize
        # instead of silently cut off.
        root.minsize(480, 360)
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        # winfo_screenheight() is the raw display height, not the usable
        # work area (taskbar, window chrome eat into it) — trim a fixed
        # margin rather than guess exactly, then still cap to a sane
        # maximum so the window doesn't balloon on a huge monitor.
        init_w = min(600, screen_w - 80)
        init_h = min(820, screen_h - 120)
        root.geometry(f"{init_w}x{init_h}")
        root.resizable(True, True)

        self._preview_image = None  # keep a reference so Tk doesn't GC it
        self._live_polling = False
        self._poll_after_id = None
        self._config = agent_config.load()
        self._templates = templates.load()

        self.container = self._build_scrollable_container()

        self._build_printer_section()
        self._build_live_mode_section()
        self._build_label_fields()
        self._build_actions()
        self._build_templates_section()
        self._build_preview()
        self._build_log()

        self._log("Ready.")
        self.refresh_printers()

    def _build_scrollable_container(self) -> ttk.Frame:
        """A Canvas+Scrollbar wrapping a Frame that every _build_* method
        below packs into (instead of self.root directly) — so content
        taller than the window is reachable by scrolling (mouse wheel or
        the scrollbar) rather than simply invisible below the window edge.
        """
        canvas = tk.Canvas(self.root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        container = ttk.Frame(canvas)
        container_window = canvas.create_window((0, 0), window=container, anchor="nw")

        def on_container_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            # Stretch the inner frame to the canvas's visible width so
            # child widgets packed with fill="x" actually reach it, instead
            # of staying at their natural (narrower) size.
            canvas.itemconfigure(container_window, width=event.width)

        container.bind("<Configure>", on_container_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        def on_mousewheel(event):
            # Windows delivers <MouseWheel> with event.delta in multiples
            # of 120; this agent is Windows-only (see module docstring),
            # so no <Button-4>/<Button-5> fallback is needed.
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_mousewheel)

        return container

    # ── Printer selection ────────────────────────────────────────────────
    def _build_printer_section(self):
        frame = ttk.LabelFrame(self.container, text="Printer (this PC)")
        frame.pack(fill="x", padx=12, pady=(12, 6))

        self.printer_var = tk.StringVar()
        self.printer_combo = ttk.Combobox(frame, textvariable=self.printer_var, state="readonly", width=48)
        self.printer_combo.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        ttk.Button(frame, text="Refresh", command=self.refresh_printers).grid(row=0, column=1, padx=8, pady=8)
        ttk.Button(frame, text="🗑️ Clear Print Queue", command=self.clear_print_queue).grid(row=0, column=2, padx=(0, 8), pady=8)

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

    def clear_print_queue(self):
        """Cancels every job in the selected printer's local Windows print
        queue -- e.g. after a jam, a wrong-printer mistake, or several
        force-print/Print Included jobs piled up unwanted. Does not touch
        anything server-side (the broker's pending print_jobs for Live
        Mode) -- only this PC's own OS-level print spooler."""
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return
        try:
            count = printing.pending_job_count(printer)
        except Exception as exc:
            messagebox.showerror("Clear Print Queue", f"Couldn't read '{printer}''s queue: {exc}")
            return
        if count == 0:
            messagebox.showinfo("Clear Print Queue", f"'{printer}' has no pending jobs.")
            return
        if not messagebox.askyesno(
            "Clear Print Queue", f"Cancel all {count} pending job(s) on '{printer}'? This can't be undone.",
        ):
            return
        try:
            cleared = printing.clear_print_queue(printer)
        except Exception as exc:
            self._log(f"❌ Clear Print Queue failed for '{printer}': {exc}")
            messagebox.showerror("Clear Print Queue", str(exc))
            return
        self._log(f"🗑️ Cleared {cleared}/{count} pending job(s) from '{printer}'.")
        self._log(f"Found {len(printers)} printer(s): {', '.join(printers) or '(none)'}")

    # ── Live Mode (poll the broker) ──────────────────────────────────────
    def _build_live_mode_section(self):
        frame = ttk.LabelFrame(self.container, text="Live Mode (poll broker for real scans)")
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

        # device_name is what shows up in the Streamlit app's "Print to
        # which desk?" picker — give it something a tech can recognize
        # (e.g. "Front Desk", "Room 12"), not the raw device_id below.
        ttk.Label(frame, text="Device Name", width=14).grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.device_name_var = tk.StringVar(value=self._config["device_name"])
        ttk.Entry(frame, textvariable=self.device_name_var, width=38).grid(row=2, column=1, padx=8, pady=4, sticky="w")

        # device_id is generated once by agent_config.load() and persisted —
        # shown read-only just so it's visible/copyable for troubleshooting.
        ttk.Label(frame, text="Device ID", width=14).grid(row=3, column=0, padx=8, pady=4, sticky="w")
        device_id_entry = ttk.Entry(frame, width=38)
        device_id_entry.insert(0, self._config["device_id"])
        device_id_entry.configure(state="readonly")
        device_id_entry.grid(row=3, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(frame, text="Poll every (sec)", width=14).grid(row=4, column=0, padx=8, pady=4, sticky="w")
        self.poll_interval_var = tk.IntVar(value=self._config["poll_interval_seconds"])
        ttk.Spinbox(frame, from_=2, to=60, textvariable=self.poll_interval_var, width=6).grid(
            row=4, column=1, padx=8, pady=4, sticky="w"
        )

        self.live_status_var = tk.StringVar(value="Stopped")
        ttk.Label(frame, textvariable=self.live_status_var).grid(row=5, column=0, padx=8, pady=(4, 8), sticky="w")
        self.live_toggle_btn = ttk.Button(frame, text="▶ Start", command=self.toggle_live_mode)
        self.live_toggle_btn.grid(row=5, column=1, padx=8, pady=(4, 8), sticky="w")

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
        device_name = self.device_name_var.get().strip()
        if not broker_url or not device_token:
            messagebox.showwarning("Missing config", "Broker URL and Device Token are both required.")
            return
        if not device_name:
            messagebox.showwarning("Missing config", "Device Name is required — it's what shows up in the Streamlit app's device picker.")
            return
        if not self.printer_var.get():
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return

        self._config["device_name"] = device_name  # device_id is never edited, only device_name
        agent_config.save({
            "broker_url": broker_url,
            "device_token": device_token,
            "device_id": self._config["device_id"],
            "device_name": device_name,
            "poll_interval_seconds": self.poll_interval_var.get(),
        })

        self._live_polling = True
        self.live_toggle_btn.configure(text="⏹ Stop")
        self._log(f"Live Mode started as '{device_name}' — polling {broker_url} every {self.poll_interval_var.get()}s.")
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
        device_id = self._config["device_id"]
        device_name = self.device_name_var.get().strip()
        printer = self.printer_var.get()

        try:
            jobs = broker.list_pending(broker_url, device_token, device_id, device_name)
        except Exception as exc:
            self.live_status_var.set(f"Error (retrying): {exc}")
            self._log(f"⚠️ Poll failed: {exc}")
            jobs = []
        else:
            self.live_status_var.set(f"Polling as '{device_name}' — last check {datetime.now().strftime('%H:%M:%S')}, {len(jobs)} pending")

        for job in jobs:
            self._print_job(broker_url, device_token, device_id, printer, job)

        if self._live_polling:
            self._poll_after_id = self.root.after(self.poll_interval_var.get() * 1000, self._poll_once)

    def _print_job(self, broker_url: str, device_token: str, device_id: str, printer: str, job: dict):
        data = label.LabelData(
            camera_number=job.get("camera_number") or "—",
            serial_number=job.get("serial_number") or "",
            model_number=job.get("model_number") or "",
            site_name=job.get("site_name") or "",
            loc_code=job.get("loc_code") or "",
            ip_address=job.get("ip_address") or "",  # not in the broker's job payload yet — always "" for now
        )
        try:
            img = label.render_label(data)
            printing.print_image(printer, img, job_name=f"Camera Label {data.camera_number}")
        except Exception as exc:
            self._log(f"❌ Print failed for job {job.get('job_id')}: {exc}")
            return  # leave it pending — will retry next poll

        try:
            broker.ack(broker_url, device_token, job["job_id"], device_id)
        except Exception as exc:
            self._log(f"⚠️ Printed {data.camera_number} but ack failed (may reprint next poll): {exc}")
            return

        self._log(f"🖨️ Printed + acked: {data.camera_number} / {data.serial_number}")

        # Included templates (see the Templates section's Include checkbox)
        # also fire on a real scan, by design -- best-effort and logged on
        # its own; a failure here never un-acks or retries the primary job
        # above, which already succeeded. Substituted from this job's real
        # scan data (not the Label fields section, which is irrelevant here).
        included = [t for t in self._templates if t.get("include", True)]
        if included:
            values = templates.build_placeholder_values({
                "camera_number": job.get("camera_number") or "",
                "serial_number": job.get("serial_number") or "",
                "model_number": job.get("model_number") or "",
                "site_name": job.get("site_name") or "",
                "loc_code": job.get("loc_code") or "",
                "ip_address": job.get("ip_address") or "",
            })
            ok = self._print_templates(printer, included, values, context_label=data.camera_number)
            self._log(f"📑 Included templates for {data.camera_number}: {ok}/{len(included)} sent.")

    def _on_close(self):
        self._live_polling = False
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
        self.root.destroy()

    # ── Label fields (manual test input) ────────────────────────────────
    def _build_label_fields(self):
        frame = ttk.LabelFrame(self.container, text="Label fields (manual test input)")
        frame.pack(fill="x", padx=12, pady=6)

        self.fields: dict[str, tk.StringVar] = {}
        rows = [
            ("camera_number", "Camera Number", "CAM06"),
            ("serial_number", "Serial Number", "B8A44F9C9745"),
            ("model_number", "Model Number", "P3827-PVE"),
            ("site_name", "Site Name", "Will Rogers Continuation High"),
            ("loc_code", "Loc Code", "8895"),
            # Not part of render_label's fixed layout (see LabelData) --
            # exists purely as a value for a template's {ip_address}
            # placeholder. A real Live Mode scan doesn't carry this yet
            # (the broker's job payload has no ip_address field), so it
            # only has real content here, from a manual trigger.
            ("ip_address", "IP Address", "10.20.30.40"),
        ]
        for i, (key, label_text, default) in enumerate(rows):
            ttk.Label(frame, text=label_text, width=16).grid(row=i, column=0, padx=8, pady=4, sticky="w")
            var = tk.StringVar(value=default)
            ttk.Entry(frame, textvariable=var, width=36).grid(row=i, column=1, padx=8, pady=4, sticky="w")
            self.fields[key] = var

    def _current_label_data(self) -> label.LabelData:
        return label.LabelData(**{key: var.get().strip() for key, var in self.fields.items()})

    # ── Actions ───────────────────────────────────────────────────────────
    def _build_actions(self):
        frame = ttk.Frame(self.container)
        frame.pack(fill="x", padx=12, pady=6)
        ttk.Button(frame, text="🔍 Preview", command=self.preview).pack(side="left", padx=4)
        ttk.Button(frame, text="🖨️ Print", command=self.print_now).pack(side="left", padx=4)

        ttk.Label(frame, text="Copies").pack(side="left", padx=(16, 4))
        # This is also what "💾 Save As New" (below) captures as a new
        # template's copies count, and what "📥 Load Selected" writes back
        # here -- one visible control doing double duty rather than a
        # second copies field living only inside the Templates section.
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(frame, from_=1, to=99, textvariable=self.copies_var, width=4).pack(side="left")

    def preview(self):
        img = label.render_label(self._current_label_data())
        thumb = img.copy()
        thumb.thumbnail((480, 240))
        self._preview_image = ImageTk.PhotoImage(thumb)
        self.preview_label.configure(image=self._preview_image)
        self._log("Preview updated.")

    def _copies_count(self) -> int:
        try:
            n = int(self.copies_var.get())
        except (tk.TclError, ValueError):
            n = 1
        return max(1, n)

    def print_now(self):
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return
        copies = self._copies_count()
        data = self._current_label_data()
        img = label.render_label(data)
        self._print_copies(printer, img, copies, job_label=data.camera_number or "Camera Label")

    def _print_copies(self, printer: str, img, copies: int, job_label: str) -> bool:
        """Prints an already-rendered image `copies` times. Returns whether
        every copy succeeded. A mid-batch failure (e.g. printer went
        offline) stops that template's remaining copies but doesn't raise
        -- lets _print_selected_templates keep going to the next template.
        Takes a pre-rendered image (not a LabelData) so callers can use
        either the classic fixed layout or a template's custom one -- see
        _render_template."""
        for i in range(copies):
            try:
                job_name = f"Camera Label {job_label}" + (f" ({i + 1}/{copies})" if copies > 1 else "")
                printing.print_image(printer, img, job_name=job_name)
            except Exception as exc:
                self._log(f"❌ Print failed for '{job_label}' (copy {i + 1}/{copies}): {exc}")
                if i == 0:
                    messagebox.showerror("Print failed", str(exc))
                return False
        suffix = f" x{copies}" if copies > 1 else ""
        self._log(f"✅ Sent '{job_label}'{suffix} to '{printer}'.")
        if printer == "Microsoft Print to PDF" and copies > 1:
            self._log(f"  → Windows will prompt its 'Save Print Output As' dialog {copies} times (once per copy).")
        elif printer == "Microsoft Print to PDF":
            self._log("  → Windows should now prompt a 'Save Print Output As' dialog.")
        return True

    # ── Templates ────────────────────────────────────────────────────────
    # "Include" (☑/☐, toggled via double-click or 🔁 Toggle Include) is a
    # persistent per-template flag, not a selection — it drives 🖨️ Print
    # Included *and* a real Live Mode scan (see _print_job), without having
    # to reselect anything each time. Print Selected (ctrl/shift-click on
    # the list) is the separate, ad hoc path for a one-off batch that
    # doesn't match whatever's currently marked Include.
    def _build_templates_section(self):
        frame = ttk.LabelFrame(self.container, text="📑 Templates")
        frame.pack(fill="x", padx=12, pady=6)

        ttk.Label(
            frame,
            text=(
                "Fields may use {camera_number} {serial_number} {model_number} {site_name} {loc_code} {ip_address}"
                " — filled in from the Label fields above (or, for Included templates, from a real scan) when "
                "printed. Also: {location_code} (same as loc_code) and {serial_last4} (last 4 of serial_number)."
            ),
            wraplength=520, justify="left", foreground="#555",
        ).pack(fill="x", padx=8, pady=(8, 4))

        self.templates_listbox = tk.Listbox(frame, height=6, selectmode="extended", exportselection=False)
        self.templates_listbox.pack(fill="x", padx=8, pady=4)
        self.templates_listbox.bind("<Double-Button-1>", self._on_template_double_click)

        btn_row1 = ttk.Frame(frame)
        btn_row1.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Button(btn_row1, text="➕ New Template", command=self._new_template).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row1, text="✏️ Edit Selected", command=self._edit_selected_template).pack(side="left", padx=4)
        ttk.Button(btn_row1, text="📥 Load Selected", command=self._load_template).pack(side="left", padx=4)
        ttk.Button(btn_row1, text="🔁 Toggle Include", command=self._toggle_include_selected).pack(side="left", padx=4)
        ttk.Button(btn_row1, text="🎨 Edit Layout", command=self._edit_selected_layout).pack(side="left", padx=4)

        btn_row2 = ttk.Frame(frame)
        btn_row2.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Button(btn_row2, text="🖨️ Print Selected", command=self._print_selected_templates).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row2, text="🖨️ Print Included", command=self._print_included_now).pack(side="left", padx=4)
        ttk.Button(btn_row2, text="🗑️ Delete Selected", command=self._delete_selected_templates).pack(side="left", padx=4)

        self._refresh_template_list()

    def _refresh_template_list(self):
        selected = set(self._selected_template_indices()) if hasattr(self, "templates_listbox") else set()
        self.templates_listbox.delete(0, "end")
        for t in self._templates:
            copies = t.get("copies", 1)
            glyph = "☑" if t.get("include", True) else "☐"
            if t.get("layout"):
                # A custom layout replaces the fixed fields entirely for
                # rendering (see _render_template) -- showing them here
                # would misleadingly imply they still apply.
                summary = f"🎨 custom layout ({len(t['layout'])} element(s))"
            else:
                cam = t.get("camera_number") or "—"
                model = t.get("model_number") or ""
                summary = f"{cam:<14} {model}"
            self.templates_listbox.insert("end", f"{glyph} {t.get('name', '(unnamed)'):<22} x{copies:<3} {summary}")
        for i in selected:
            if i < self.templates_listbox.size():
                self.templates_listbox.selection_set(i)

    def _selected_template_indices(self) -> list[int]:
        return [int(i) for i in self.templates_listbox.curselection()]

    def _on_template_double_click(self, _event):
        # tk selects the clicked row before this fires, so a plain
        # double-click always toggles exactly the row under the cursor —
        # even if it changes what was previously selected.
        indices = self._selected_template_indices()
        if len(indices) == 1:
            self._toggle_include([indices[0]])

    def _toggle_include_selected(self):
        indices = self._selected_template_indices()
        if not indices:
            messagebox.showwarning("Toggle Include", "Select one or more templates first.")
            return
        self._toggle_include(indices)

    def _toggle_include(self, indices: list[int]):
        for i in indices:
            self._templates[i]["include"] = not self._templates[i].get("include", True)
        templates.save(self._templates)
        self._refresh_template_list()

    def _new_template(self):
        self._open_template_editor(None)

    def _edit_selected_template(self):
        indices = self._selected_template_indices()
        if len(indices) != 1:
            messagebox.showwarning("Edit Template", "Select exactly one template to edit.")
            return
        self._open_template_editor(indices[0])

    def _open_template_editor(self, existing_index: int | None):
        """Shared Add/Edit dialog. `existing_index is None` -> new template,
        prefilled from the current Label fields + Copies (the same starting
        point the old one-click Save used to capture directly) so a tech can
        still just click New + Save for a plain snapshot, or edit any field
        into a placeholder first. Otherwise edits self._templates[existing_index]
        in place."""
        existing = self._templates[existing_index] if existing_index is not None else None

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Template" if existing else "New Template")
        dialog.transient(self.root)
        dialog.grab_set()  # modal — Save/Cancel below is the only way out

        def prefill(key: str) -> str:
            if existing is not None:
                return existing.get(key, "")
            return self.fields[key].get()  # new template: start from what's on screen now

        name_var = tk.StringVar(value=existing.get("name", "") if existing else "")
        field_vars = {key: tk.StringVar(value=prefill(key)) for key in self.fields}
        copies_var = tk.IntVar(value=existing.get("copies", self._copies_count()) if existing else self._copies_count())
        include_var = tk.BooleanVar(value=existing.get("include", True) if existing else True)

        row = 0
        ttk.Label(
            dialog,
            text=(
                "Placeholders: {camera_number} {serial_number} {model_number} {site_name} {loc_code} {ip_address}\n"
                "Also: {location_code} (same as loc_code), {serial_last4} (last 4 of serial_number)"
            ),
            justify="left", foreground="#555",
        ).grid(row=row, column=0, columnspan=2, padx=10, pady=(10, 6), sticky="w")
        row += 1

        if existing and existing.get("layout"):
            ttk.Label(
                dialog,
                text="⚠ This template has a custom layout (🎨 Edit Layout) — the fields below are ignored when printing.",
                foreground="#a60", wraplength=440, justify="left",
            ).grid(row=row, column=0, columnspan=2, padx=10, pady=(0, 6), sticky="w")
            row += 1

        ttk.Label(dialog, text="Name", width=14).grid(row=row, column=0, padx=10, pady=4, sticky="w")
        ttk.Entry(dialog, textvariable=name_var, width=42).grid(row=row, column=1, padx=10, pady=4, sticky="w")
        row += 1

        field_labels = [
            ("camera_number", "Camera Number"), ("serial_number", "Serial Number"),
            ("model_number", "Model Number"), ("site_name", "Site Name"), ("loc_code", "Loc Code"),
            ("ip_address", "IP Address"),
        ]
        for key, text in field_labels:
            ttk.Label(dialog, text=text, width=14).grid(row=row, column=0, padx=10, pady=4, sticky="w")
            ttk.Entry(dialog, textvariable=field_vars[key], width=42).grid(row=row, column=1, padx=10, pady=4, sticky="w")
            row += 1

        copies_row = row
        ttk.Label(dialog, text="Copies", width=14).grid(row=copies_row, column=0, padx=10, pady=4, sticky="w")
        ttk.Spinbox(dialog, from_=1, to=99, textvariable=copies_var, width=6).grid(row=copies_row, column=1, padx=10, pady=4, sticky="w")
        row += 1

        ttk.Checkbutton(
            dialog, text='Include (fires from "🖨️ Print Included" and from a real scan)', variable=include_var,
        ).grid(row=row, column=0, columnspan=2, padx=10, pady=(4, 10), sticky="w")
        row += 1
        btn_grid_row = row

        def do_save():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Name required", "Give this template a name.", parent=dialog)
                return
            collision_idx = next(
                (i for i, t in enumerate(self._templates) if t.get("name") == name and i != existing_index), None
            )
            if collision_idx is not None and not messagebox.askyesno(
                "Overwrite template?", f"A template named '{name}' already exists. Overwrite it?", parent=dialog
            ):
                return

            new_template = {
                "name": name,
                **{key: var.get() for key, var in field_vars.items()},
                "copies": max(1, copies_var.get()),
                "include": include_var.get(),
            }
            if existing and existing.get("layout"):
                new_template["layout"] = existing["layout"]  # this dialog never touches layout — carry it forward
            if existing_index is not None:
                self._templates[existing_index] = new_template
                if collision_idx is not None:
                    del self._templates[collision_idx]  # assigned above by original index — safe either order
            elif collision_idx is not None:
                self._templates[collision_idx] = new_template
            else:
                self._templates.append(new_template)

            templates.save(self._templates)
            self._refresh_template_list()
            self._log(f"💾 Saved template '{name}'.")
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.grid(row=btn_grid_row, column=0, columnspan=2, pady=(0, 10))
        ttk.Button(btn_row, text="Save", command=do_save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        dialog.bind("<Return>", lambda _e: do_save())
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

    # ── Layout editor ────────────────────────────────────────────────────
    def _edit_selected_layout(self):
        indices = self._selected_template_indices()
        if len(indices) != 1:
            messagebox.showwarning("Edit Layout", "Select exactly one template to edit its layout.")
            return
        self._open_layout_editor(indices[0])

    def _open_layout_editor(self, template_index: int):
        """Free-form layout editor: drag text elements around a 1:1-scale
        canvas of the label's native 600x300 space (label.WIDTH_PX/
        HEIGHT_PX), edit each one's text/size/alignment/bold, add/remove
        elements. Works on a local `working` list -- only written back to
        self._templates[template_index]["layout"] (and persisted) on
        Save, same non-destructive-Cancel pattern as _open_template_editor.
        An empty layout on Save clears any existing custom layout back to
        the classic fixed rendering (see _render_template)."""
        t = self._templates[template_index]
        working: list[dict] = [dict(el) for el in (t.get("layout") or [])]
        selected_idx = [None]  # boxed so nested handlers can read/write it

        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Layout — {t.get('name', '(unnamed)')}")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(
            dialog,
            text=(
                "Drag an element to reposition it. Placeholders: {camera_number} {serial_number} {model_number}\n"
                "{site_name} {loc_code} {ip_address} {location_code} {serial_last4}"
            ),
            justify="left", foreground="#555",
        ).pack(padx=10, pady=(10, 6), anchor="w")

        canvas = tk.Canvas(
            dialog, width=label.WIDTH_PX, height=label.HEIGHT_PX,
            background="white", highlightthickness=1, highlightbackground="#999",
        )
        canvas.pack(padx=10, pady=2)

        add_row = ttk.Frame(dialog)
        add_row.pack(fill="x", padx=10, pady=4)
        ttk.Button(add_row, text="➕ Add Text Element", command=lambda: add_element()).pack(side="left", padx=(0, 4))
        ttk.Button(add_row, text="🔍 Preview", command=lambda: do_preview()).pack(side="left", padx=4)
        ttk.Button(add_row, text="↺ Clear All (back to classic)", command=lambda: clear_all()).pack(side="left", padx=4)

        # ── Element property panel ──
        props = ttk.LabelFrame(dialog, text="Selected element")
        props.pack(fill="x", padx=10, pady=6)

        text_var = tk.StringVar()
        size_var = tk.IntVar(value=24)
        align_var = tk.StringVar(value="left")
        bold_var = tk.BooleanVar(value=True)

        ttk.Label(props, text="Text", width=10).grid(row=0, column=0, padx=8, pady=4, sticky="w")
        text_entry = ttk.Entry(props, textvariable=text_var, width=44)
        text_entry.grid(row=0, column=1, columnspan=3, padx=8, pady=4, sticky="w")

        ttk.Label(props, text="Font size", width=10).grid(row=1, column=0, padx=8, pady=4, sticky="w")
        size_spin = ttk.Spinbox(props, from_=8, to=200, textvariable=size_var, width=6)
        size_spin.grid(row=1, column=1, padx=8, pady=4, sticky="w")

        ttk.Label(props, text="Align").grid(row=1, column=2, padx=(16, 4), pady=4, sticky="e")
        align_combo = ttk.Combobox(
            props, textvariable=align_var, values=["left", "center", "right"], state="disabled", width=8,
        )
        align_combo.grid(row=1, column=3, padx=4, pady=4, sticky="w")

        bold_check = ttk.Checkbutton(props, text="Bold", variable=bold_var)
        bold_check.grid(row=2, column=1, padx=8, pady=4, sticky="w")
        remove_btn = ttk.Button(props, text="🗑️ Remove Element", command=lambda: remove_selected())
        remove_btn.grid(row=2, column=3, padx=8, pady=4, sticky="e")

        preview_frame = ttk.LabelFrame(dialog, text="Preview")
        preview_frame.pack(fill="x", padx=10, pady=(0, 6))
        preview_label_widget = ttk.Label(preview_frame)
        preview_label_widget.pack(padx=8, pady=8)
        preview_image_ref = [None]  # keep a reference so Tk doesn't GC it

        anchor_map = {"left": "w", "center": "center", "right": "e"}
        _suspend_trace = [False]  # guards against on_prop_change firing while select_element is populating the vars

        def set_props_enabled(enabled: bool):
            text_entry.configure(state="normal" if enabled else "disabled")
            size_spin.configure(state="normal" if enabled else "disabled")
            align_combo.configure(state="readonly" if enabled else "disabled")
            bold_check.configure(state="normal" if enabled else "disabled")
            remove_btn.configure(state="normal" if enabled else "disabled")

        def redraw_canvas():
            canvas.delete("all")
            canvas.create_rectangle(2, 2, label.WIDTH_PX - 2, label.HEIGHT_PX - 2, outline="#ccc")
            for idx, el in enumerate(working):
                weight = "bold" if el.get("bold", True) else "normal"
                item = canvas.create_text(
                    el.get("x", 0), el.get("y", 0), text=el.get("text", "") or "(empty)",
                    font=("Arial", max(1, int(el.get("font_size", 24))), weight),
                    anchor=anchor_map.get(el.get("align", "left"), "w"),
                    fill="#1a56db" if idx == selected_idx[0] else "black",
                )
                canvas.tag_bind(item, "<ButtonPress-1>", lambda e, i=idx: start_drag(e, i))
                canvas.tag_bind(item, "<B1-Motion>", lambda e, i=idx: do_drag(e, i))

        def select_element(idx):
            selected_idx[0] = idx
            _suspend_trace[0] = True
            if idx is None:
                text_var.set("")
                set_props_enabled(False)
            else:
                el = working[idx]
                text_var.set(el.get("text", ""))
                size_var.set(el.get("font_size", 24))
                align_var.set(el.get("align", "left"))
                bold_var.set(el.get("bold", True))
                set_props_enabled(True)
            _suspend_trace[0] = False
            redraw_canvas()

        def on_canvas_click(event):
            # Tkinter tags whatever's directly under the cursor "current" --
            # empty means the click missed every element, i.e. deselect.
            # Item clicks are handled by each element's own tag_bind above
            # via start_drag, which also selects -- this only ever fires
            # the deselect branch in practice.
            if not canvas.find_withtag("current"):
                select_element(None)

        canvas.bind("<ButtonPress-1>", on_canvas_click)

        drag_state = {"idx": None, "start_x": 0, "start_y": 0, "orig_x": 0, "orig_y": 0}

        def start_drag(event, idx):
            select_element(idx)
            drag_state.update(idx=idx, start_x=event.x, start_y=event.y, orig_x=working[idx]["x"], orig_y=working[idx]["y"])

        def do_drag(event, idx):
            if drag_state["idx"] != idx:
                return
            working[idx]["x"] = max(0, min(label.WIDTH_PX, drag_state["orig_x"] + (event.x - drag_state["start_x"])))
            working[idx]["y"] = max(0, min(label.HEIGHT_PX, drag_state["orig_y"] + (event.y - drag_state["start_y"])))
            redraw_canvas()

        def on_prop_change(*_args):
            if _suspend_trace[0]:
                return
            idx = selected_idx[0]
            if idx is None:
                return
            working[idx]["text"] = text_var.get()
            try:
                working[idx]["font_size"] = max(1, int(size_var.get()))
            except (tk.TclError, ValueError):
                pass
            working[idx]["align"] = align_var.get()
            working[idx]["bold"] = bold_var.get()
            redraw_canvas()

        text_var.trace_add("write", on_prop_change)
        size_var.trace_add("write", on_prop_change)
        align_var.trace_add("write", on_prop_change)
        bold_var.trace_add("write", on_prop_change)

        def add_element():
            working.append({
                "text": "{camera_number}", "x": label.WIDTH_PX // 2, "y": label.HEIGHT_PX // 2,
                "font_size": 32, "align": "center", "bold": True,
            })
            select_element(len(working) - 1)

        def remove_selected():
            idx = selected_idx[0]
            if idx is None:
                return
            del working[idx]
            select_element(None)

        def clear_all():
            if working and not messagebox.askyesno(
                "Clear All", "Remove every element? This reverts to the classic fixed layout once saved.", parent=dialog,
            ):
                return
            working.clear()
            select_element(None)

        def do_preview():
            values = self._current_field_values()
            elements = [{**el, "text": templates.apply_placeholders(el.get("text", ""), values)} for el in working]
            img = label.render_label_custom(elements) if elements else label.render_label(self._current_label_data())
            thumb = img.copy()
            thumb.thumbnail((480, 240))
            preview_image_ref[0] = ImageTk.PhotoImage(thumb)
            preview_label_widget.configure(image=preview_image_ref[0])

        def do_save():
            if working:
                t["layout"] = working
            else:
                t.pop("layout", None)
            templates.save(self._templates)
            self._refresh_template_list()
            self._log(f"🎨 Saved layout for '{t.get('name')}' ({len(working)} element(s)).")
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(pady=(0, 10))
        ttk.Button(btn_row, text="Save", command=do_save).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancel", command=dialog.destroy).pack(side="left", padx=6)
        dialog.bind("<Escape>", lambda _e: dialog.destroy())

        redraw_canvas()

    def _load_template(self):
        indices = self._selected_template_indices()
        if len(indices) != 1:
            messagebox.showwarning("Load Template", "Select exactly one template to load.")
            return
        t = self._templates[indices[0]]
        for key in self.fields:
            self.fields[key].set(t.get(key, ""))
        self.copies_var.set(t.get("copies", 1))
        self._log(f"📥 Loaded template '{t.get('name')}' into the fields above (placeholders load as literal text).")

    def _render_template(self, t: dict, values: dict):
        """Renders one template — its custom free-form layout if it has
        one (non-empty "layout"), else the classic fixed 5-slot layout —
        with placeholders in either substituted from `values`. Every
        template that predates the layout editor has no "layout" key, so
        this is the single dispatch point that keeps them rendering
        exactly as before."""
        layout = t.get("layout")
        if layout:
            elements = [
                {**el, "text": templates.apply_placeholders(el.get("text", ""), values)}
                for el in layout
            ]
            return label.render_label_custom(elements)
        data = label.LabelData(**{
            key: templates.apply_placeholders(t.get(key, ""), values) for key in self.fields
        })
        return label.render_label(data)

    def _print_templates(self, printer: str, template_list: list[dict], values: dict, context_label: str) -> int:
        """Renders + prints each template in template_list — placeholders
        substituted from `values` — its own saved copies count each.
        Returns how many fully succeeded; a per-template failure (e.g.
        printer went offline mid-batch) is logged and skipped rather than
        aborting the rest (see _print_copies)."""
        ok = 0
        for t in template_list:
            img = self._render_template(t, values)
            copies = max(1, int(t.get("copies", 1)))
            job_label = f"{t.get('name', 'template')} [{context_label}]"
            if self._print_copies(printer, img, copies, job_label=job_label):
                ok += 1
        return ok

    def _current_field_values(self) -> dict:
        raw = {key: var.get().strip() for key, var in self.fields.items()}
        return templates.build_placeholder_values(raw)

    def _print_selected_templates(self):
        indices = self._selected_template_indices()
        if not indices:
            messagebox.showwarning("Print Selected", "Select one or more templates first (ctrl/shift-click for multiple).")
            return
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return

        selected = [self._templates[i] for i in indices]
        total_copies = sum(max(1, int(t.get("copies", 1))) for t in selected)
        if not messagebox.askyesno(
            "Print Selected", f"Print {len(selected)} template(s), {total_copies} label(s) total, to '{printer}'?",
        ):
            return
        ok_count = self._print_templates(printer, selected, self._current_field_values(), context_label="selected")
        self._log(f"🖨️ Print Selected: {ok_count}/{len(selected)} template(s) sent successfully.")

    def _print_included_now(self):
        included = [t for t in self._templates if t.get("include", True)]
        if not included:
            messagebox.showinfo("Print Included", "No templates are marked Include (☑) — nothing to print.")
            return
        printer = self.printer_var.get()
        if not printer:
            messagebox.showwarning("No printer selected", "Pick a printer first.")
            return
        total_copies = sum(max(1, int(t.get("copies", 1))) for t in included)
        if not messagebox.askyesno(
            "Print Included", f"Print {len(included)} included template(s), {total_copies} label(s) total, to '{printer}'?",
        ):
            return
        ok_count = self._print_templates(printer, included, self._current_field_values(), context_label="included")
        self._log(f"🖨️ Print Included: {ok_count}/{len(included)} template(s) sent successfully.")

    def _delete_selected_templates(self):
        indices = self._selected_template_indices()
        if not indices:
            messagebox.showwarning("Delete Selected", "Select one or more templates first.")
            return
        names = ", ".join(self._templates[i].get("name", "?") for i in indices)
        if not messagebox.askyesno("Delete Selected", f"Delete {len(indices)} template(s): {names}?"):
            return
        for i in sorted(indices, reverse=True):
            del self._templates[i]
        templates.save(self._templates)
        self._refresh_template_list()
        self._log(f"🗑️ Deleted {len(indices)} template(s).")

    # ── Preview + log widgets ────────────────────────────────────────────
    def _build_preview(self):
        frame = ttk.LabelFrame(self.container, text="Preview")
        frame.pack(fill="x", padx=12, pady=6)
        self.preview_label = ttk.Label(frame)
        self.preview_label.pack(padx=8, pady=8)

    def _build_log(self):
        frame = ttk.LabelFrame(self.container, text="Log")
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
