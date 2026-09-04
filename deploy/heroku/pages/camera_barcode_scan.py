"""camera_barcode_scan.py — Step 3 of the Camera Asset Intake workflow.

Records each box's serial-number barcode as it's scanned. A USB/Bluetooth
barcode scanner types into a focused text input like a keyboard and sends
Enter, so a plain st.text_input with clear_on_submit is enough — no
special scanner integration needed. Model/manufacturer are asked for
per scan since barcode payloads vary by vendor and box label; adjust
this form once you know your scanners' actual output format.
"""

import pandas as pd
import streamlit as st

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Camera Asset Intake")

site = st.session_state.get("cctv_site")
if not site:
    st.warning("No site selected yet — go back and pick a site first.")
    st.stop()

loc_code = site["loc_code"]
st.subheader(f"📷 Scan received hardware for {site['site_name']} ({loc_code})")

with st.form("scan_form", clear_on_submit=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        serial = st.text_input("Serial Number (scan here)", autocomplete="off")
    with c2:
        model = st.text_input("Model / Part Number")
    with c3:
        manufacturer = st.selectbox("Manufacturer", ["Axis", "Genetec", "Other"])
    mac = st.text_input("MAC Address (optional — scan if the box has a MAC barcode)")
    submitted = st.form_submit_button("➕ Add scan", type="primary")

    if submitted:
        if not serial or not model:
            st.error("Serial Number and Model are both required.")
        else:
            cctv.add_scanned_asset(
                loc_code, serial, model,
                manufacturer=manufacturer,
                mac_address=mac or None,
            )
            st.toast(f"Recorded {serial}", icon="✅")

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
    "Next step suggests a camera number for each unassigned item by matching "
    "its model against the uploaded Camera Chart — you'll confirm or override "
    "every suggestion there."
)
