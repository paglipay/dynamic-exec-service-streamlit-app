import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st

PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")
if PAGE_DIR not in sys.path:
    sys.path.insert(0, PAGE_DIR)

assistant_module_path = os.path.join(PAGE_DIR, "_ai_assistant_panel.py")
assistant_spec = importlib.util.spec_from_file_location(
    "assistant_panel", assistant_module_path
)
assistant_mod = importlib.util.module_from_spec(assistant_spec)
assistant_spec.loader.exec_module(assistant_mod)
render_ai_assistant_panel = assistant_mod.render_ai_assistant_panel

theme_module_path = os.path.join(PAGE_DIR, "_theme.py")
theme_spec = importlib.util.spec_from_file_location("theme_panel", theme_module_path)
theme_mod = importlib.util.module_from_spec(theme_spec)
theme_spec.loader.exec_module(theme_mod)
apply_page_theme = theme_mod.apply_page_theme


def inject_launcher_styles() -> None:
    """Apply launcher-only card layout styles on top of the shared theme."""
    st.markdown(
        """
        <style>
            .section-card {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 1rem 1.1rem;
                box-shadow: 0 10px 24px var(--shadow);
            }

            .section-heading {
                margin: 0 0 0.45rem 0;
                color: var(--text);
                font-size: 1rem;
                letter-spacing: 0.01em;
            }

            .section-copy {
                margin: 0;
                color: var(--muted);
                font-size: 0.92rem;
            }

            div[data-baseweb="select"] > div {
                border-color: var(--border) !important;
                background: var(--surface-soft) !important;
                color: var(--text) !important;
                border-radius: 10px !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_page_theme(
    "Dynamic Streamlit App Launcher",
    "Browse apps, inspect source, and launch modules from the pages directory.",
    layout="wide",
    toggle_key="launcher_theme_toggle",
)
inject_launcher_styles()
render_ai_assistant_panel("Multi-App Launcher")

# Get list of Python files in pages folder.
app_files = sorted(
    [
        f
        for f in os.listdir(PAGE_DIR)
        if f.endswith(".py") and not Path(f).name.startswith("_")
    ]
)

left_col, right_col = st.columns([1.05, 1.35], gap="large")

with left_col:
    st.markdown(
        """
        <div class="section-card">
            <h3 class="section-heading">App Picker</h3>
            <p class="section-copy">Choose a module from pages and run its app() entrypoint.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    selected_app = st.selectbox("Select app", app_files)

with right_col:
    st.markdown(
        """
        <div class="section-card">
            <h3 class="section-heading">Live Preview</h3>
            <p class="section-copy">Source and output are shown below for the selected app.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

if selected_app:
    app_path = os.path.join(PAGE_DIR, selected_app)

    st.markdown(f"### {selected_app}")

    with open(app_path, "r", encoding="utf-8") as file:
        code = file.read()
    st.code(code, language="python")

    try:
        module_name = f"page_{Path(selected_app).stem}"
        spec = importlib.util.spec_from_file_location(module_name, app_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)

        if hasattr(mod, "app"):
            mod.app()
        else:
            st.warning("Selected app does not have an 'app' function to run.")

    except Exception as exc:
        st.error(f"Failed to run app: {exc}")
