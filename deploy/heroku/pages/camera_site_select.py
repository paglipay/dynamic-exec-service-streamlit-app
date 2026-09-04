"""camera_site_select.py — Step 1 of the Camera Asset Intake workflow.

Picks the school site this intake session is for. Reads the existing
`r1_data` site directory (read-only — same collection google_earth.py
uses) and stores the choice in st.session_state["cctv_site"], which the
rest of this workflow's steps read from.
"""

import streamlit as st

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Camera Asset Intake")

st.subheader("📍 Select a school site")

sites = cctv.list_sites()

if not sites:
    st.warning(
        "No sites loaded. Ensure `MONGODB_URI` is set (via `.streamlit/secrets.toml` "
        "or an environment variable) and the `r1_data` collection is reachable."
    )
else:
    labels = [
        f"{s.get('School Name') or s.get('Site') or 'Unknown'} ({s.get('Loc Code', '')})"
        for s in sites
    ]
    current = st.session_state.get("cctv_site")
    default_idx = 0
    if current:
        for i, s in enumerate(sites):
            if str(s.get("Loc Code")) == str(current.get("loc_code")):
                default_idx = i
                break

    idx = st.selectbox("School site", options=range(len(sites)), format_func=lambda i: labels[i], index=default_idx)
    chosen = sites[idx]
    loc_code = str(chosen.get("Loc Code", "")).strip()
    site_name = chosen.get("School Name") or chosen.get("Site") or ""

    st.session_state["cctv_site"] = {"loc_code": loc_code, "site_name": site_name}

    st.success(f"Selected: **{site_name}** (Loc Code `{loc_code}`)")
    with st.expander("Site details"):
        st.json({k: v for k, v in chosen.items()})

st.caption(
    "Don't see the site you need? It comes from the same school directory "
    "used by the Google Earth tool — check there, or ask an admin to add it."
)
