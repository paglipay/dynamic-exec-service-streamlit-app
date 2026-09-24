"""camera_file_upload.py — Step 2 of the Camera Asset Intake workflow.

Upload the Asset Workbook (.xlsm, "New_Equipment" sheet) and/or the
Camera Chart (.xlsm, "Cam Chart" sheet). Parses each, previews the
result, flags a Location Code mismatch against the selected site, and
on confirmation upserts into cctv_camera_assets / cctv_camera_chart.
"""

import pandas as pd
import streamlit as st

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Camera Asset Intake")

site = st.session_state.get("cctv_site")
if not site:
    st.warning("No site selected yet — go back to the previous step and pick a site first.")
    st.stop()

loc_code = site["loc_code"]
st.subheader(f"📤 Upload files for {site['site_name']} ({loc_code})")

col_a, col_b = st.columns(2)

# ── Asset Workbook ───────────────────────────────────────────────────────────
with col_a:
    st.markdown("**Asset Workbook** (`.xlsm`)")
    asset_file = st.file_uploader("Reads the `New_Equipment` sheet", type=["xlsm", "xlsx"], key="cctv_asset_upload")
    if asset_file is not None:
        try:
            rows = cctv.parse_asset_workbook(asset_file.getvalue())
        except Exception as exc:
            st.error(f"Could not parse Asset Workbook: {exc}")
            rows = []
        if rows:
            file_locs = {r["loc_code"] for r in rows if r["loc_code"]}
            if file_locs and loc_code not in file_locs:
                st.warning(
                    f"⚠️ This file's Location Code(s) {sorted(file_locs)} don't match "
                    f"the selected site ({loc_code}). Double-check you picked the right site/file."
                )
            st.dataframe(
                pd.DataFrame(rows)[
                    ["camera_id_raw", "manufacturer", "model_number", "serial_number", "mac_address", "ip_address"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"{len(rows)} asset rows parsed.")
            if st.button("💾 Save asset rows to database", key="save_assets"):
                n = cctv.upsert_camera_assets_rows(loc_code, rows)
                st.success(f"Saved {n} asset rows to `cctv_camera_assets` for site {loc_code}.")
        else:
            st.info("No populated rows found in `New_Equipment`.")

# ── Camera Chart ─────────────────────────────────────────────────────────────
with col_b:
    st.markdown("**Camera Chart** (`.xlsm`)")
    chart_file = st.file_uploader("Reads the `Cam Chart` sheet", type=["xlsm", "xlsx"], key="cctv_chart_upload")
    if chart_file is not None:
        try:
            rows, site_line = cctv.parse_camera_chart(chart_file.getvalue())
        except Exception as exc:
            st.error(f"Could not parse Camera Chart: {exc}")
            rows, site_line = [], ""
        if rows:
            if site_line and loc_code not in site_line:
                st.warning(
                    f"⚠️ This file's site line reads \"{site_line}\", which doesn't "
                    f"obviously match the selected site ({loc_code}). Double-check."
                )
            st.dataframe(
                pd.DataFrame(rows)[["camera_id_raw", "building", "camera_model_text", "mount_type", "data_cabinet"]],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"{len(rows)} camera rows parsed.")
            if st.button("💾 Save camera chart to database", key="save_chart"):
                n = cctv.upsert_camera_chart_rows(loc_code, rows)
                st.success(f"Saved {n} camera rows to `cctv_camera_chart` for site {loc_code}.")
        else:
            st.info("No populated rows found in `Cam Chart`.")

st.divider()
st.caption(
    "Uploading again re-parses the file but does **not** save automatically — "
    "review the preview, then click each Save button. Saving is an upsert keyed "
    "by (site, camera ID) / (site, serial number), so re-uploading a corrected "
    "file safely overwrites the matching rows."
)
