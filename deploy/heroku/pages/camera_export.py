"""camera_export.py — Step 5 (final) of the Camera Asset Intake workflow.

Pulls this site's confirmed data back out of cctv_camera_assets /
cctv_camera_chart and offers it as a download shaped like the Asset
Workbook's New_Equipment sheet, for pasting back into the real .xlsm
hand-off document (this tool does not write into the original .xlsm —
LAUSD's turnover process expects that file to come from the licensed
template, not a regenerated copy).
"""

import io

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
st.subheader(f"📥 Export — {site['site_name']} ({loc_code})")

assets = cctv.get_camera_assets(loc_code)
chart = cctv.get_camera_chart(loc_code)

assigned = [a for a in assets if a.get("camera_id")]
unassigned = [a for a in assets if not a.get("camera_id")]
open_slots = [c for c in chart if c.get("status") == "planned"]

m1, m2, m3 = st.columns(3)
m1.metric("Assigned", len(assigned))
m2.metric("Received, unassigned", len(unassigned))
m3.metric("Open Camera Chart slots", len(open_slots))

if unassigned:
    st.warning(f"{len(unassigned)} scanned item(s) still have no camera number — finish the Assign step first for a complete export.")

# Shape to match the Asset Workbook's New_Equipment column order.
COLUMNS = [
    ("camera_id_raw", "AP Number"),
    ("manufacturer", "Manufacturer"),
    ("model_number", "Model Number"),
    ("serial_number", "Serial Number"),
    ("mac_address", "MAC Address"),
    ("ip_address", "IP Address"),
    ("host_name", "Host Name (DNS Name)"),
    ("building", "Building"),
    ("floor", "Floor"),
    ("room_number", "Room Number"),
    ("cafm_room_number", "CAFM Room Number"),
    ("cabinet", "Cabinet"),
    ("component_of", "Component Of"),
    ("equipment_category", "Equipment Category"),
    ("status", "Status"),
]

rows = []
for a in assets:
    row = {label: a.get(key) for key, label in COLUMNS}
    row["AP Number"] = f"CAM{a['camera_id']['num']}{a['camera_id']['letter']}" if a.get("camera_id") else a.get("camera_id_raw")
    rows.append(row)

df = pd.DataFrame(rows, columns=[label for _, label in COLUMNS])
st.dataframe(df, use_container_width=True, hide_index=True)

col1, col2 = st.columns(2)
with col1:
    st.download_button(
        "⬇️ Download CSV",
        df.to_csv(index=False).encode("utf-8"),
        file_name=f"{loc_code}_camera_assets.csv",
        mime="text/csv",
        use_container_width=True,
    )
with col2:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="New_Equipment")
    st.download_button(
        "⬇️ Download XLSX",
        buf.getvalue(),
        file_name=f"{loc_code}_camera_assets.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
