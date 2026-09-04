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

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Camera Asset Intake")

site = st.session_state.get("cctv_site")
if not site:
    st.warning("No site selected yet — go back and pick a site first.")
    st.stop()

loc_code = site["loc_code"]
MANUFACTURER = "Axis"

st.subheader(f"📷 Scan received hardware for {site['site_name']} ({loc_code})")

with st.expander("🔌 Test print-broker connection (no scan/chart needed)"):
    st.caption(
        "Sends one dummy job straight to the broker's /print-jobs, bypassing "
        "auto-assign entirely — for checking Heroku → broker → local agent "
        "connectivity on its own, independent of any real scan or Camera Chart."
    )
    if st.button("🖨️ Send test print job"):
        test_result = cctv.enqueue_print_job(
            site["site_name"], loc_code, {"num": 0, "letter": ""}, "TEST-SERIAL", "TEST-MODEL",
        )
        if test_result["ok"]:
            st.success("✅ Enqueued — check the local print agent's Live Mode log for CAM0 / TEST-SERIAL.")
        else:
            st.error(f"❌ {test_result['error']}")


def _finish_row(serial: str, model: str, **extra) -> dict:
    """Save one scanned/typed Model+Serial row, attempt scan-time
    auto-assign (see _cctv_data.auto_assign_on_scan's docstring for why
    this always picks the lowest matching slot, ambiguous or not), and
    — if assigned — enqueue a print job. Never raises; a broker/network
    failure is reported back, not fatal to the scan loop, so scanning
    keeps working even if printing doesn't."""
    cctv.add_scanned_asset(loc_code, serial, model, manufacturer=MANUFACTURER, **extra)
    result = {"serial": serial, "model": model, "camera_number": None, "print_ok": None, "print_error": None}

    camera_id = cctv.auto_assign_on_scan(loc_code, serial)
    if camera_id:
        camera_number = f"CAM{camera_id['num']}{camera_id['letter']}"
        result["camera_number"] = camera_number
        printed = cctv.enqueue_print_job(site["site_name"], loc_code, camera_id, serial, model)
        result["print_ok"] = printed["ok"]
        result["print_error"] = printed["error"]
    return result


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
