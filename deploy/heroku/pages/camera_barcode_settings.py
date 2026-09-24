"""camera_barcode_settings.py — Barcode classification rules for the
Camera Asset Intake workflow's image-upload scan path
(camera_barcode_scan.py).

A decoded barcode's raw text doesn't say whether it's a Model or a
Serial Number — these rules do that classification. Ordered; the first
regex (Python re.search) that matches wins. A catch-all ".*" rule is
required as the last entry so every decoded value always lands
somewhere — get_barcode_rules() re-adds one automatically if it's ever
missing, but this page also blocks removing the very last row so that
can't happen from here.

Global, not per-site: barcode format is a property of the Axis hardware
line, not the school, so one rule set applies everywhere.
"""

import pandas as pd
import streamlit as st

from _auth_guard import require_authentication
import _cctv_data as cctv

require_authentication("Barcode Classification Settings")

st.title("⚙️ Barcode Classification Settings")
st.caption(
    "Rules for classifying a decoded barcode (from the Scan step's image "
    "upload) as a Model or Serial Number. Evaluated top to bottom — first "
    "match wins. Applies to every site."
)

rules = cctv.get_barcode_rules()
df = pd.DataFrame(rules)
if "case_insensitive" not in df.columns:
    df["case_insensitive"] = True

edited = st.data_editor(
    df,
    column_config={
        "pattern": st.column_config.TextColumn("Regex pattern", required=True, width="medium"),
        "field": st.column_config.SelectboxColumn(
            "Classifies as", options=["serial_number", "model_number", "ignore"], required=True,
        ),
        "label": st.column_config.TextColumn("Label (for display only)"),
        "case_insensitive": st.column_config.CheckboxColumn("Case-insensitive", default=True),
    },
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key="barcode_rules_editor",
)

st.caption(
    "The last row should stay a catch-all (pattern `.*`) so every barcode "
    "classifies as *something* — if you remove it, saving adds one back "
    "automatically, defaulted to Model Number."
)

if st.button("💾 Save rules", type="primary"):
    new_rules = edited.to_dict("records")
    new_rules = [r for r in new_rules if str(r.get("pattern") or "").strip()]
    if not any(r.get("pattern") == ".*" for r in new_rules):
        new_rules.append({
            "pattern": ".*", "field": "model_number",
            "label": "Model Number (default)", "case_insensitive": True,
        })
        st.info("Added back a catch-all `.*` → Model Number rule at the end.")
    cctv.save_barcode_rules(new_rules)
    st.success(f"Saved {len(new_rules)} rule(s).")
    st.rerun()

st.divider()
st.subheader("🧪 Test a value")
test_value = st.text_input("Paste a decoded barcode value to see which rule catches it")
if test_value:
    field = cctv.classify_barcode(test_value, rules=edited.to_dict("records"))
    if field == "serial_number":
        st.success("→ **Serial Number**")
    elif field == "model_number":
        st.info("→ **Model Number**")
    elif field == "ignore":
        st.warning("→ **Ignored** (e.g. an EAN-13 retail barcode) — dropped, not treated as Model or Serial.")
    else:
        st.warning("No rule matched (this shouldn't happen once a catch-all is saved).")
