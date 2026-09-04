import importlib.util
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()  # local dev convenience only; no-op if no .env is present.
    # Production and `streamlit run` prefer .streamlit/secrets.toml
    # (st.secrets) — see each page's `_get_secret()` helper.
except ImportError:
    pass

import streamlit as st

st.set_page_config(
    page_title="Contractor Tool Kit",
    page_icon="🔧",
    layout="wide",
)

PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
if PAGE_DIR not in sys.path:
    sys.path.insert(0, PAGE_DIR)

# Workflows live one level up from pages/, in their own folder. Each
# subfolder of WORKFLOWS_DIR that contains workflow.yaml becomes one
# auto-discovered workflow card under the "🧭 Workflows" section.
WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflows"
)


def discover_workflows() -> list[tuple[str, dict]]:
    """Return [(slug, spec_dict), ...] sorted by slug, skipping bad specs."""
    out: list[tuple[str, dict]] = []
    if not os.path.isdir(WORKFLOWS_DIR):
        return out
    try:
        import yaml  # local import so a missing dep doesn't kill the home page
    except ImportError:
        return out
    for slug in sorted(os.listdir(WORKFLOWS_DIR)):
        wdir = os.path.join(WORKFLOWS_DIR, slug)
        spec_path = os.path.join(wdir, "workflow.yaml")
        if not os.path.isfile(spec_path):
            continue
        try:
            with open(spec_path, "r", encoding="utf-8") as fh:
                spec = yaml.safe_load(fh)
        except Exception:
            continue
        if isinstance(spec, dict) and isinstance(spec.get("steps"), list):
            out.append((slug, spec))
    return out


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
if "selected_workflow" not in st.session_state:
    st.session_state["selected_workflow"] = None

selected = st.session_state["selected_app"]
selected_workflow = st.session_state["selected_workflow"]

# ── Home: card grid ────────────────────────────────────────────────────────
if not selected and not selected_workflow:
    st.title("🔧 Contractor Tool Kit")
    st.caption("Select a tool below to get started.")
    st.divider()

    # ── Workflows section (auto-discovered) — shown first ───────────────────
    workflows = discover_workflows()
    if workflows:
        st.markdown(
            '<div class="ctk-section">🧭 Workflows</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns(COLS)
        for i, (slug, spec) in enumerate(workflows):
            icon = spec.get("icon", "🧭")
            name = spec.get("name", slug)
            label = f"{icon} {name}"
            with cols[i % COLS]:
                if st.button(label, key=f"wf_card_{slug}", use_container_width=True):
                    st.session_state["selected_workflow"] = slug
                    # Always start a fresh workflow from step 0
                    st.session_state.pop(f"_wf_step_{slug}", None)
                    st.rerun()

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

# ── Workflow view ──────────────────────────────────────────────────────────
elif selected_workflow:
    runner_path = os.path.join(PAGE_DIR, "_workflow_runner.py")

    if st.button("← Back to Tool Kit"):
        # Reset both step counter and selected workflow so re-entry is clean
        st.session_state.pop(f"_wf_step_{selected_workflow}", None)
        st.session_state["selected_workflow"] = None
        st.rerun()

    st.divider()

    try:
        spec = importlib.util.spec_from_file_location(
            "workflow_runner_mod", runner_path,
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["workflow_runner_mod"] = mod
        spec.loader.exec_module(mod)
    except Exception as exc:
        st.error(f"Failed to load workflow runner: {exc}")

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
