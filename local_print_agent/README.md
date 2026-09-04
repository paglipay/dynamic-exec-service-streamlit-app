# Camera Label Print Agent

A local, Windows-only GUI that lists the intake PC's installed
printers, polls the print-job broker for real scans from the Camera
Asset Intake workflow, and prints a label for each one.

**Why this has to be local:** the Streamlit app runs on Heroku, so its
server process has no access to any desktop's hardware — same reason
`serial_console.py` in the main app only reaches real serial ports when
someone runs `streamlit run` locally, not once it's deployed. A label
printer at the intake desk needs an agent running on that desk's own
PC, which is what this is.

**How a scan becomes a printed label:**
1. `camera_barcode_scan.py` (Streamlit) auto-assigns a camera number
   right after a Model+Serial pair is scanned, and POSTs a job to the
   broker (`_cctv_data.py`'s `enqueue_print_job()`).
2. The broker is the sibling `slack-to-onedrive-sync` repo's
   `/print-jobs` endpoints (REST + polling, not WebSocket — matches
   that service's existing job pattern rather than adding
   infrastructure it doesn't have).
3. This agent, in **Live Mode**, polls `GET /print-jobs/pending` on an
   interval, prints each job's label, and POSTs `.../ack`.

## Setup

```
cd local_print_agent
pip install -r requirements.txt
python print_agent.py
```

Windows only (`pywin32`). This is intentionally a **separate**
`requirements.txt` from the main repo's — `pywin32` would break the
Heroku (Linux) build if it ended up in the root one.

## Live Mode

Fill in:
- **Broker URL** — the `slack-to-onedrive-sync` service's base URL
  (e.g. `http://127.0.0.1:5000` running it locally, or its Heroku URL
  once deployed).
- **Device Token** — that service's `DEVICE_TOKEN` (same secret the
  site-cam PWA uses; ask whoever manages that deploy, or read it from
  that repo's `.env`/Heroku config vars). **Not** `TRIGGER_SECRET` —
  that one gates *enqueuing* jobs (used by the Streamlit app), and this
  agent only *polls/acks*, a different, device-scoped permission.
- **Device Name** — a human-readable label for this PC/printer (e.g.
  "Front Desk", "Room 12 Intake"). Defaults to this machine's hostname.
  This is exactly what shows up in the Streamlit app's **"Print to
  which desk?"** picker — so with multiple intake desks running their
  own agent, this is how a tech there tells them apart.
- **Device ID** — auto-generated once, shown read-only. Stays stable
  across restarts (persisted in `agent_config.json`) — this, not the
  name, is what the broker actually uses to route jobs to *this*
  agent specifically and no other. Don't edit it; if you ever need a
  clean slate, delete `agent_config.json` and a new one is generated.
- **Poll every (sec)** — how often to check for new jobs.

Click **▶ Start**. These fields save to `agent_config.json`
(gitignored — holds a live token, never commit it) so you don't have to
retype them next launch.

**Multiple desks:** run this agent on each intake PC, each with its own
Device Name (Device ID is generated per-machine automatically) and its
own printer selected. A device only appears in the Streamlit app's
picker after it's polled at least once, so start Live Mode *before*
scanning at that desk. Jobs are routed by device_id — even two desks
working the same site concurrently only ever print what they
themselves scanned, never each other's.

## Testing with Microsoft Print to PDF

Pick **Microsoft Print to PDF** from the printer dropdown before
starting Live Mode (or before clicking **Print** in the manual section
below it). Windows will pop its own **"Save Print Output As"** dialog
per job — that's the driver's own behavior, not something this code
controls or can suppress. A real label printer won't do that. In Live
Mode, that dialog pops for *every* pending job in sequence, so it's
easiest to test with one job queued at a time until you're ready for a
real label printer.

## Manual fields (no broker needed)

The "Label fields" section further down still works independently of
Live Mode — type values in and click **Preview**/**Print** to test the
printer/rendering path on its own.

## Files

- `print_agent.py` — the Tkinter GUI (printer picker, Live Mode
  polling, manual label fields, preview, print, log).
- `broker.py` — HTTP client for the broker's `/print-jobs/pending` +
  `/print-jobs/<id>/ack`.
- `agent_config.py` — loads/saves `agent_config.json` (broker URL,
  device token, poll interval).
- `printing.py` — printer enumeration + sending a `PIL.Image` to a
  selected printer via raw GDI drawing (`win32print`/`win32ui`), so it
  works against any installed printer without relying on file-type
  associations.
- `label.py` — renders the label as a `PIL.Image`. Size (4in × 2in @
  300 DPI) and layout are placeholders until a real label printer/stock
  is chosen — no barcode yet either; both are easy to add once those
  specs are known.

## Known limitations

- No barcode on the label yet, text only.
- Label size/DPI are guesses (4×2in @ 300 DPI) — adjust `label.py`'s
  `WIDTH_IN`/`HEIGHT_IN`/`DPI` once real label stock is chosen.
- Font lookup tries a couple of common Windows fonts (`arialbd.ttf`,
  `arial.ttf`, `seguisb.ttf`) and falls back to PIL's tiny built-in
  bitmap font if none are found — labels will look much rougher on a
  machine without those fonts installed.
- A job that fails to print (e.g. printer offline) stays pending and
  gets retried next poll — a job that prints but fails to ack could
  print again on the next poll (logged either way, not silent).
