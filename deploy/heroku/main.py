import importlib.util
import os
import sys
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Streamlit Multi-App Launcher",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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


def inject_theme_styles(theme_mode: str) -> None:
    """Apply a custom visual system for light and dark modes."""
    if theme_mode == "dark":
        palette = {
            "bg": "#0b1220",
            "bg_grad_1": "#0f1a2f",
            "bg_grad_2": "#08101d",
            "surface": "#121c30",
            "surface_soft": "#0f1729",
            "text": "#e5eefc",
            "muted": "#9eb1d4",
            "primary": "#67d5b5",
            "primary_hover": "#7be2c4",
            "border": "#22324f",
            "shadow": "rgba(0, 0, 0, 0.35)",
            "code_bg": "#0a1324",
        }
    else:
        palette = {
            "bg": "#f6f8fc",
            "bg_grad_1": "#ffffff",
            "bg_grad_2": "#eef4ff",
            "surface": "#ffffff",
            "surface_soft": "#f4f7ff",
            "text": "#0e1a32",
            "muted": "#5f6f8e",
            "primary": "#0b84f3",
            "primary_hover": "#2b95f4",
            "border": "#d7e0f2",
            "shadow": "rgba(16, 33, 66, 0.08)",
            "code_bg": "#f1f5ff",
        }

    st.markdown(
        f"""
        <style>
            :root {{
                --bg: {palette['bg']};
                --bg-grad-1: {palette['bg_grad_1']};
                --bg-grad-2: {palette['bg_grad_2']};
                --surface: {palette['surface']};
                --surface-soft: {palette['surface_soft']};
                --text: {palette['text']};
                --muted: {palette['muted']};
                --primary: {palette['primary']};
                --primary-hover: {palette['primary_hover']};
                --border: {palette['border']};
                --shadow: {palette['shadow']};
                --code-bg: {palette['code_bg']};
            }}

            .stApp {{
                background:
                    radial-gradient(circle at 15% 20%, var(--bg-grad-2), transparent 40%),
                    radial-gradient(circle at 85% 5%, var(--bg-grad-2), transparent 35%),
                    linear-gradient(160deg, var(--bg-grad-1) 0%, var(--bg) 100%);
                color: var(--text);
            }}

            .block-container {{
                padding-top: 1.4rem;
                padding-bottom: 2.2rem;
                max-width: 1200px;
            }}

            .hero {{
                background: linear-gradient(135deg, var(--surface) 0%, var(--surface-soft) 100%);
                border: 1px solid var(--border);
                border-radius: 18px;
                padding: 1rem 1.25rem;
                box-shadow: 0 12px 30px var(--shadow);
                margin-bottom: 1rem;
            }}

            .hero h1 {{
                margin: 0;
                font-size: clamp(1.4rem, 2vw, 2rem);
                color: var(--text);
            }}

            .hero p {{
                margin: 0.35rem 0 0 0;
                color: var(--muted);
                font-size: 0.95rem;
            }}

            .section-card {{
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 1rem 1.1rem;
                box-shadow: 0 10px 24px var(--shadow);
            }}

            .section-heading {{
                margin: 0 0 0.45rem 0;
                color: var(--text);
                font-size: 1rem;
                letter-spacing: 0.01em;
            }}

            .section-copy {{
                margin: 0;
                color: var(--muted);
                font-size: 0.92rem;
            }}

            div[data-baseweb="select"] > div {{
                border-color: var(--border) !important;
                background: var(--surface-soft) !important;
                color: var(--text) !important;
                border-radius: 10px !important;
            }}

            .stButton > button {{
                background: var(--primary);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 0.45rem 1rem;
                font-weight: 600;
            }}

            .stButton > button:hover {{
                background: var(--primary-hover);
            }}

            [data-testid="stCodeBlock"] pre,
            [data-testid="stCode"] pre {{
                background: var(--code-bg) !important;
                border: 1px solid var(--border) !important;
                border-radius: 12px !important;
            }}

            .stAlert {{
                border-radius: 12px;
                border: 1px solid var(--border);
            }}

            @media (max-width: 840px) {{
                .block-container {{
                    padding-top: 1rem;
                    padding-left: 0.8rem;
                    padding-right: 0.8rem;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "light"

header_left, header_right = st.columns([5, 1])
with header_left:
    st.markdown(
        """
        <div class="hero">
            <h1>Dynamic Streamlit App Launcher</h1>
            <p>Browse apps, inspect source, and launch modules from the pages directory.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
with header_right:
    dark_mode_enabled = st.toggle(
        "Dark mode",
        value=st.session_state.theme_mode == "dark",
        help="Switch between light and dark visual themes.",
    )
    st.session_state.theme_mode = "dark" if dark_mode_enabled else "light"

inject_theme_styles(st.session_state.theme_mode)
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
