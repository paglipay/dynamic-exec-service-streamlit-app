"""camera_assign_review.py — Step 4 of the Camera Asset Intake workflow.

Suggests a camera number for each scanned-but-unassigned asset by
matching its model against the site's Camera Chart, and lets a human
confirm or override every suggestion before anything is committed.

⚠️ The matching heuristic (substring match of Model Number inside the
Camera Chart's Camera Model text) is UNVALIDATED against a real
same-site Camera-Chart + Asset-Workbook pair — see _cctv_data.py's
suggest_assignments() docstring. Treat every suggestion here as a
starting point, not a fact.
"""

import streamlit as st

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Camera Asset Intake")

site = st.session_state.get("cctv_site")
if not site:
    st.warning("No site selected yet — go back and pick a site first.")
    st.stop()

loc_code = site["loc_code"]
st.subheader(f"🎯 Assign camera numbers — {site['site_name']} ({loc_code})")
st.info(
    "Suggestions are a starting point (model-text match against the Camera Chart), "
    "**not verified**. Review every row before confirming.",
    icon="⚠️",
)

suggestions = cctv.suggest_assignments(loc_code)

if not suggestions:
    st.success("Nothing to assign — either every scanned item already has a camera number, or none are scanned yet.")
    st.stop()

for item in suggestions:
    asset = item["asset"]
    candidates = item["candidates"]
    with st.container(border=True):
        c1, c2 = st.columns([2, 3])
        with c1:
            st.markdown(f"**{asset['serial_number']}**")
            st.caption(f"{asset.get('manufacturer', '')} {asset.get('model_number', '')}")
        with c2:
            if not candidates:
                st.warning("No open Camera Chart slot matches this model.")
                continue

            options = {c["camera_id"]["canonical"]: c for c in candidates}
            labels = {
                canon: f"Camera {canon} — {c.get('building', '')} / {c.get('cabinet_room_location', '')}"
                for canon, c in options.items()
            }
            choice = st.radio(
                "Assign to:",
                options=list(options.keys()),
                format_func=lambda k: labels[k],
                key=f"choice_{asset['serial_number']}",
                horizontal=False,
            )
            if st.button("✅ Confirm this assignment", key=f"confirm_{asset['serial_number']}"):
                ok = cctv.confirm_assignment(loc_code, asset["serial_number"], choice)
                if ok:
                    st.success(f"{asset['serial_number']} → Camera {choice}")
                    st.rerun()
                else:
                    st.error("That slot or asset was already claimed elsewhere — refreshing.")
                    st.rerun()
