"""camera_barcode_scan.py — Step 3 of the Camera Asset Intake workflow.

Records each box's barcodes as they're scanned. Axis camera boxes carry
two barcodes — Model/Part Number and Serial Number — so the scanner
window walks through them as a strict two-step, repeating loop: scan
Model -> scan Serial -> saved -> back to Model for the next camera. A
USB/Bluetooth barcode scanner types into the focused input like a
keyboard and sends Enter, which submits the form — no special scanner
integration needed.

Manufacturer is fixed to "Axis" for now — this intake flow is scoped to
Axis camera equipment only; re-introduce a manufacturer choice here if
that scope changes.
"""

import io
import zipfile

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from _auth_guard import require_authentication
import _cctv_data as cctv

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp")

# Each unresolved image runs OCR (ONNX inference, the slow step) inside the
# same request/response — there's no background job queue here. Heroku's
# router hard-kills any request past 30s (H12) regardless of dyno type, so
# an unbounded zip could kill the whole batch partway through with nothing
# saved for the images after the cutoff. Capped well under that budget;
# raise it only alongside a background-processing rework of this expander.
_MAX_BATCH_IMAGES = 25

require_authentication("Camera Asset Intake")

site = st.session_state.get("cctv_site")
if not site:
    st.warning("No site selected yet — go back and pick a site first.")
    st.stop()

loc_code = site["loc_code"]
MANUFACTURER = "Axis"

st.subheader(f"📷 Scan received hardware for {site['site_name']} ({loc_code})")

# ── Print device picker ─────────────────────────────────────────────────
# Every print agent has its own device_id (local_print_agent/agent_config.py)
# and jobs are routed to exactly one — otherwise every running agent would
# grab every job and duplicate-print across every printer in the building.
# A device only shows up here once it's polled at least once, so start
# that desk's Live Mode before scanning.
devices = cctv.list_print_devices()
col_dev, col_refresh = st.columns([4, 1])
with col_dev:
    if devices:
        device_labels = {d["device_id"]: d["device_name"] for d in devices}
        options = list(device_labels.keys())
        current = st.session_state.get("cctv_print_device")
        default_idx = options.index(current) if current in options else 0
        chosen = st.selectbox(
            "🖨️ Print to which desk?", options=options, index=default_idx,
            format_func=lambda k: device_labels[k],
        )
        st.session_state["cctv_print_device"] = chosen
    else:
        st.session_state["cctv_print_device"] = None
        st.warning(
            "No print agents online — start local_print_agent's Live Mode on the "
            "intake desk's PC first (it needs to poll at least once before it "
            "shows up here)."
        )
with col_refresh:
    st.write("")  # vertical spacer to align the button with the selectbox
    if st.button("🔄", help="Refresh device list"):
        st.rerun()

st.session_state.setdefault("cctv_force_print", False)
st.checkbox(
    "🔧 Force print even without a Camera Chart match (testing)",
    key="cctv_force_print",
    help=(
        "Normally a row only prints once auto-assign finds a matching Camera "
        "Chart slot. Turn this on to send a print job for every row regardless "
        "— useful for exercising the Heroku → broker → local agent → printer "
        "flow end-to-end before a real Camera Chart is uploaded. The label "
        "prints \"UNASSIGNED\" instead of a real camera number."
    ),
)

with st.expander("🔌 Test print-broker connection (no scan/chart needed)"):
    st.caption(
        "Sends one dummy job straight to the broker's /print-jobs, bypassing "
        "auto-assign entirely — for checking Heroku → broker → local agent "
        "connectivity on its own, independent of any real scan or Camera Chart. "
        "Uses whichever desk is selected above."
    )
    if st.button("🖨️ Send test print job"):
        test_result = cctv.enqueue_print_job(
            site["site_name"], loc_code, {"num": 0, "letter": ""}, "TEST-SERIAL", "TEST-MODEL",
            device_id=st.session_state.get("cctv_print_device"),
        )
        if test_result["ok"]:
            st.success("✅ Enqueued — check the selected desk's print agent Live Mode log for CAM0 / TEST-SERIAL.")
        else:
            st.error(f"❌ {test_result['error']}")


def _finish_row(serial: str, model: str, **extra) -> dict:
    """Save one scanned/typed Model+Serial row, attempt scan-time
    auto-assign (see _cctv_data.auto_assign_on_scan's docstring for why
    this always picks the lowest matching slot, ambiguous or not), and
    — if assigned, or "Force print" is on — enqueue a print job. Never
    raises; a broker/network failure is reported back, not fatal to the
    scan loop, so scanning keeps working even if printing doesn't."""
    cctv.add_scanned_asset(loc_code, serial, model, manufacturer=MANUFACTURER, **extra)
    result = {"serial": serial, "model": model, "camera_number": None, "print_ok": None, "print_error": None}

    camera_id = cctv.auto_assign_on_scan(loc_code, serial)
    if camera_id:
        result["camera_number"] = f"CAM{camera_id['num']}{camera_id['letter']}"
        printed = cctv.enqueue_print_job(
            site["site_name"], loc_code, camera_id, serial, model,
            device_id=st.session_state.get("cctv_print_device"),
        )
        result["print_ok"] = printed["ok"]
        result["print_error"] = printed["error"]
    elif st.session_state.get("cctv_force_print"):
        result["camera_number"] = "UNASSIGNED"
        result["forced"] = True
        printed = cctv.enqueue_print_job(
            site["site_name"], loc_code, None, serial, model,
            device_id=st.session_state.get("cctv_print_device"),
            camera_number_override="UNASSIGNED",
        )
        result["print_ok"] = printed["ok"]
        result["print_error"] = printed["error"]
    return result


def _process_barcode_image(label: str, image_bytes: bytes, rules: list) -> dict:
    """Decode+classify one label photo's barcodes (falling back to OCR text
    on the same photo when barcode decoding alone doesn't resolve both
    fields), and — if exactly one Model and one Serial resolve — save+
    auto-assign+print the row via _finish_row, same as the single-image
    path this replaces. Never raises; returns a dict describing the
    outcome for display. `label` is just what identifies this image in the
    results list (a plain filename, or "zipname:member" for a zip entry)."""
    decoded = cctv.decode_barcodes_from_image(image_bytes)
    models, serials, other = [], [], []
    for text in decoded:
        field = cctv.classify_barcode(text, rules)
        if field == "model_number":
            models.append(text)
        elif field == "serial_number":
            serials.append(text)
        elif field == "ignore":
            continue  # e.g. an EAN-13 retail barcode — not model/serial, dropped
        else:
            other.append(text)

    model = models[0] if len(models) == 1 else None
    serial = serials[0] if len(serials) == 1 else None
    model_source = "barcode" if model else None
    serial_source = "barcode" if serial else None

    ocr_lines = []
    if not (model and serial):
        ocr_lines = cctv.read_text_from_image(image_bytes)
        if ocr_lines:
            ocr_result = cctv.extract_model_serial_from_text(ocr_lines, rules=rules)
            if not model and ocr_result["model"]:
                model = ocr_result["model"]
                model_source = "OCR"
            if not serial and ocr_result["serial"]:
                serial = ocr_result["serial"]
                serial_source = "OCR"

    out = {
        "label": label, "model": model, "serial": serial,
        "model_source": model_source, "serial_source": serial_source,
        "models": models, "serials": serials, "other": other, "ocr_lines": ocr_lines,
    }
    if model and serial:
        saved = _finish_row(serial, model)
        out["status"] = "ok"
        out["camera_number"] = saved["camera_number"]
        out["print_ok"] = saved["print_ok"]
        out["print_error"] = saved["print_error"]
    elif not decoded and not ocr_lines:
        out["status"] = "empty"
    else:
        out["status"] = "ambiguous"
    return out


def _autofocus(aria_label: str):
    """Best-effort: refocus the scanner's text input after every rerun, so
    a barcode scanner (type + Enter, no clicking) can keep firing scans
    back-to-back without the user ever touching the mouse/keyboard focus.
    Streamlit re-renders the DOM on every rerun and does not preserve
    focus on its own, hence this small same-origin JS poke."""
    components.html(
        f"""
        <script>
        (function() {{
            const target = {aria_label!r};
            function tryFocus() {{
                const doc = window.parent.document;
                const inputs = doc.querySelectorAll('input[aria-label]');
                for (const el of inputs) {{
                    if (el.getAttribute('aria-label') === target) {{
                        el.focus();
                        return true;
                    }}
                }}
                return false;
            }}
            let attempts = 0;
            const timer = setInterval(function() {{
                attempts += 1;
                if (tryFocus() || attempts > 30) clearInterval(timer);
            }}, 100);
        }})();
        </script>
        """,
        height=0,
    )


@st.dialog("📷 Barcode Scanner", width="large")
def _scanner_dialog():
    stage = st.session_state.get("cctv_scan_stage", "model")
    pending_model = st.session_state.get("cctv_scan_pending_model")
    last_saved = st.session_state.get("cctv_scan_last_saved")
    log = st.session_state.setdefault("cctv_scan_log", [])

    label = "Model / Part Number" if stage == "model" else "Serial Number"

    if stage == "model":
        st.info("🔦 Ready — scan the **Model / Part Number** barcode.")
    else:
        st.success(f"Model **{pending_model}** captured — now scan the **Serial Number** barcode.")

    if last_saved:
        line = f"✅ Last saved: **{last_saved['model']}** / **{last_saved['serial']}**"
        if last_saved["camera_number"]:
            line += f" → **{last_saved['camera_number']}**"
            line += " 🖨️ printed" if last_saved["print_ok"] else f" ⚠️ print failed ({last_saved['print_error']})"
        else:
            line += " — no matching Camera Chart slot yet"
        st.caption(line)

    with st.form("scanner_capture_form", clear_on_submit=True):
        value = st.text_input(label, key="cctv_scanner_input", autocomplete="off")
        submitted = st.form_submit_button("Capture", type="primary", use_container_width=True)
    _autofocus(label)

    if submitted:
        value = value.strip()
        if not value:
            st.error(f"Scan (or type) a {label.lower()} first.")
        elif stage == "model":
            st.session_state["cctv_scan_pending_model"] = value
            st.session_state["cctv_scan_stage"] = "serial"
            # scope="fragment": rerun just this dialog, not the whole app —
            # a plain st.rerun() here would close the dialog (per st.dialog's
            # own docs: "the dialog function is not called during the
            # full-script rerun").
            st.rerun(scope="fragment")
        else:
            result = _finish_row(value, pending_model)
            log.append({
                "Model": pending_model,
                "Serial Number": value,
                "Camera #": result["camera_number"] or "—",
                "Print": "🖨️" if result["print_ok"] else ("⚠️" if result["camera_number"] else "—"),
            })
            st.session_state["cctv_scan_last_saved"] = result
            st.session_state["cctv_scan_pending_model"] = None
            st.session_state["cctv_scan_stage"] = "model"
            if result["camera_number"] and result["print_ok"]:
                st.toast(f"Saved {value} → {result['camera_number']}, sent to printer", icon="🖨️")
            elif result["camera_number"]:
                st.toast(f"Saved {value} → {result['camera_number']} (print failed)", icon="⚠️")
            else:
                st.toast(f"Saved {value} (no matching Camera Chart slot yet)", icon="✅")
            st.rerun(scope="fragment")

    if log:
        st.divider()
        st.caption(f"Scanned this session: {len(log)} (most recent first)")
        st.dataframe(
            pd.DataFrame(list(reversed(log))),
            hide_index=True, use_container_width=True,
            column_order=["Model", "Serial Number", "Camera #", "Print"],
        )

    if st.button("✅ Done scanning", use_container_width=True):
        st.session_state["cctv_scan_stage"] = "model"
        st.session_state["cctv_scan_pending_model"] = None
        st.session_state["cctv_scan_log"] = []
        st.session_state["cctv_scan_last_saved"] = None
        st.rerun()


if st.button("📷 Open Barcode Scanner", type="primary", use_container_width=True):
    st.session_state["cctv_scan_stage"] = "model"
    st.session_state["cctv_scan_pending_model"] = None
    st.session_state["cctv_scan_last_saved"] = None
    _scanner_dialog()

with st.expander("🖼️ Upload barcode image"):
    st.caption(
        "Upload one or more photos of labels — or a **.zip** full of them — "
        "and each is decoded and classified automatically (rules: "
        "**⚙️ Settings → Barcode Classification Rules**; default: `B8A4`/`HW` "
        "prefixes → Serial, a 13-digit EAN retail barcode → ignored, anything "
        "else → Model). If a barcode is unreadable (glare, damage, bad angle) "
        "it falls back to reading the printed label text on the same photo — "
        "'Part No. ...'/'Model ...' and 'Serial No. .../S/N ...'. Each image "
        "that resolves exactly one Model and one Serial is auto-added "
        "immediately, same as a live scan — no confirmation step, so a "
        "misread goes straight through; re-upload a clearer photo for "
        f"anything flagged below. Capped at {_MAX_BATCH_IMAGES} images per "
        "batch (OCR is slow enough that more risks timing out the request)."
    )
    uploaded_files = st.file_uploader(
        "Barcode/label image(s), or a .zip of them",
        type=["png", "jpg", "jpeg", "bmp", "webp", "zip"],
        accept_multiple_files=True,
        key="cctv_barcode_image",
    )
    if uploaded_files:
        # Flatten to a flat (label, bytes) list first — one or more loose
        # images, one or more zips (each expanded to its image members), or
        # a mix of both — so the rest of this block processes one uniform
        # list regardless of how the batch arrived.
        images: list[tuple[str, bytes]] = []
        for f in uploaded_files:
            fname_lower = f.name.lower()
            if fname_lower.endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(f.getvalue())) as zf:
                        for member in zf.namelist():
                            member_lower = member.lower()
                            # Skip directory entries and macOS's __MACOSX/
                            # resource-fork noise, keep everything else that
                            # looks like an image.
                            if member.endswith("/") or member.startswith("__MACOSX/"):
                                continue
                            if not member_lower.endswith(_IMAGE_EXTS):
                                continue
                            images.append((f"{f.name}:{member}", zf.read(member)))
                except zipfile.BadZipFile:
                    st.error(f"❌ {f.name} isn't a valid .zip file — skipped.")
            elif fname_lower.endswith(_IMAGE_EXTS):
                images.append((f.name, f.getvalue()))
            else:
                st.warning(f"⚠️ {f.name}: unsupported file type — skipped.")

        if len(images) > _MAX_BATCH_IMAGES:
            st.warning(
                f"⚠️ {len(images)} images found — only processing the first "
                f"{_MAX_BATCH_IMAGES}. Upload the rest as a separate batch."
            )
            images = images[:_MAX_BATCH_IMAGES]

        if images:
            rules = cctv.get_barcode_rules()
            with st.spinner(f"Processing {len(images)} image(s)…"):
                results = [_process_barcode_image(label, data, rules) for label, data in images]

            ok_count = 0
            for r in results:
                if r["status"] == "ok":
                    ok_count += 1
                    note = (
                        "" if r["model_source"] == r["serial_source"] == "barcode"
                        else f" (model via {r['model_source']}, serial via {r['serial_source']})"
                    )
                    if r["camera_number"] and r["print_ok"]:
                        st.success(f"✅ **{r['label']}**: {r['model']} / {r['serial']}{note} → {r['camera_number']}, sent to printer")
                    elif r["camera_number"]:
                        st.warning(f"⚠️ **{r['label']}**: {r['model']} / {r['serial']}{note} → {r['camera_number']} (print failed: {r['print_error']})")
                    else:
                        st.info(f"✅ **{r['label']}**: {r['model']} / {r['serial']}{note} recorded — no matching Camera Chart slot yet")
                elif r["status"] == "empty":
                    st.error(f"❌ **{r['label']}**: no barcode or readable text found — try a clearer or closer photo.")
                else:
                    st.warning(
                        f"⚠️ **{r['label']}**: couldn't resolve both a Model and a Serial — "
                        f"expected exactly one of each. Add manually below, or adjust the "
                        f"rules in Settings if these are being classified wrong."
                    )
                    rows = (
                        [{"Value": t, "Source": "barcode", "Classified as": "Model"} for t in r["models"]]
                        + [{"Value": t, "Source": "barcode", "Classified as": "Serial"} for t in r["serials"]]
                        + [{"Value": t, "Source": "barcode", "Classified as": "—"} for t in r["other"]]
                        + [{"Value": t, "Source": "OCR", "Classified as": "—"} for t in r["ocr_lines"]]
                    )
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            if len(images) > 1:
                st.caption(f"{ok_count} of {len(images)} image(s) auto-added.")

with st.expander("Or enter manually"):
    with st.form("scan_form_manual", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            model = st.text_input("Model / Part Number")
        with c2:
            serial = st.text_input("Serial Number")
        mac = st.text_input("MAC Address (optional)")
        submitted = st.form_submit_button("➕ Add", type="primary")

        if submitted:
            if not serial or not model:
                st.error("Model and Serial Number are both required.")
            else:
                result = _finish_row(serial, model, mac_address=mac or None)
                if result["camera_number"] and result["print_ok"]:
                    st.toast(f"Recorded {serial} → {result['camera_number']}, sent to printer", icon="🖨️")
                elif result["camera_number"]:
                    st.toast(f"Recorded {serial} → {result['camera_number']} (print failed)", icon="⚠️")
                else:
                    st.toast(f"Recorded {serial} (no matching Camera Chart slot yet)", icon="✅")

st.divider()

assets = cctv.get_camera_assets(loc_code)
unassigned = [a for a in assets if not a.get("camera_id")]
assigned = [a for a in assets if a.get("camera_id")]

st.markdown(f"**Unassigned (received, no camera number yet): {len(unassigned)}**")
if unassigned:
    st.dataframe(
        pd.DataFrame(unassigned)[["serial_number", "model_number", "manufacturer", "mac_address", "status"]],
        use_container_width=True, hide_index=True,
    )

if assigned:
    with st.expander(f"Already assigned a camera number: {len(assigned)}"):
        st.dataframe(
            pd.DataFrame(assigned)[["serial_number", "model_number", "camera_id_raw", "status"]],
            use_container_width=True, hide_index=True,
        )

st.caption(
    "Each scan now auto-assigns a camera number and prints a label immediately "
    "(no review pause — see the Assign step for why that's a deliberate "
    "tradeoff). Anything still unassigned above had no matching Camera Chart "
    "slot yet — the Assign step handles those once the chart is uploaded."
)
