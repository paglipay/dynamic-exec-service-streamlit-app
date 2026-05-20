import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Contractor Tool Kit",
    page_icon="🔧",
    layout="wide",
)

PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
if PAGE_DIR not in sys.path:
    sys.path.insert(0, PAGE_DIR)


def _load(name: str, filename: str):
    path = os.path.join(PAGE_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


require_authentication = _load("auth_guard", "_auth_guard.py").require_authentication
render_ai_assistant_panel = _load("assistant_panel", "_ai_assistant_panel.py").render_ai_assistant_panel
_brand_mod = _load("brand", "_brand.py")
apply_branding = _brand_mod.apply_branding
render_footer = _brand_mod.render_footer

require_authentication("Contractor Tool Kit")
apply_branding()
render_ai_assistant_panel("Contractor Tool Kit")

# ── App catalog ────────────────────────────────────────────────────────────
COLS = 3

APP_CATALOG = {
    "📄 Documents": [
        ("checklist_pdf.py",  "✅ Checklist PDF"),
        ("word_template.py",  "📝 Word Template"),
        ("pdf_sign.py",       "✍️ PDF Sign"),
        ("images_pdf.py",     "📄 Images → PDF"),
        ("json_submitter.py", "📋 JSON Submitter"),
    ],
    "🖼️ Media": [
        ("cam_img_rename.py",  "📷 Camera Renamer"),
        ("image_generator.py", "🎨 Image Generator"),
        ("image_cleaner.py",   "🛡️ AI Privacy Image Cleaner"),
    ],
    "📊 Data": [
        ("data_dash.py",           "📊 Data Dashboard"),
        ("interactive_plotter.py", "📈 Plotter"),
    ],
    "🗺️ Mapping": [
        ("google_earth.py", "🌍 Google Earth"),
    ],
    "🛠️ Dev Tools": [
        ("api_explorer.py",               "🔌 API Explorer"),
        ("workflow_submitter.py",         "🔁 Workflow Submitter"),
        ("python_terminal_interactive.py", "🐍 Python Terminal"),
        ("text_processing_tool.py",        "🔤 Text Processing"),
        ("dynamic_page.py",               "⚡ Dynamic Page"),
        ("streamlit_app_maker_app.py",    "🏗️ App Maker"),
        ("ansible_basic.py",              "⚙️ Ansible"),
        ("serial_console.py",             "🖥️ Serial Console"),
    ],
    "🎯 Utilities": [
        ("to_do_list.py",       "☑️ To-Do List"),
        ("custom_game_quiz.py", "🎮 Game Quiz"),
        ("streamlit_app.py",    "📖 README Viewer"),
    ],
    "🆘 Support": [
        ("contact_support.py", "🆘 Contact & Support"),
    ],
}

# ── Session state ──────────────────────────────────────────────────────────
if "selected_app" not in st.session_state:
    st.session_state["selected_app"] = None

selected = st.session_state["selected_app"]

# ── Home: card grid ────────────────────────────────────────────────────────
if not selected:
    st.title("🔧 Contractor Tool Kit")
    st.caption("Select a tool below to get started.")
    st.divider()

    for section, apps in APP_CATALOG.items():
        existing = [(f, label) for f, label in apps if os.path.exists(os.path.join(PAGE_DIR, f))]
        if not existing:
            continue
        st.markdown(f'<div class="ctk-section">{section}</div>', unsafe_allow_html=True)
        cols = st.columns(COLS)
        for i, (filename, label) in enumerate(existing):
            with cols[i % COLS]:
                if st.button(label, key=f"card_{filename}", use_container_width=True):
                    st.session_state["selected_app"] = filename
                    st.rerun()

    render_footer()

# ── Tool view ──────────────────────────────────────────────────────────────
else:
    app_path = os.path.join(PAGE_DIR, selected)

    if st.button("← Back to Tool Kit"):
        st.session_state["selected_app"] = None
        st.rerun()

    st.divider()

    if os.getenv("STREAMLIT_SHOW_SOURCE_CODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        with st.expander("Source code", expanded=False):
            with open(app_path, "r", encoding="utf-8") as f:
                st.code(f.read(), language="python")

    try:
        spec = importlib.util.spec_from_file_location("mod", app_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["mod"] = mod
        spec.loader.exec_module(mod)

        if hasattr(mod, "app"):
            mod.app()

    except Exception as exc:
        st.error(f"Failed to load tool: {exc}")
