import streamlit as st
from streamlit.errors import StreamlitAPIException


def set_page_config_once(page_title: str, layout: str = "centered") -> None:
    """Set page config when possible; ignore duplicate calls in embedded execution."""
    try:
        st.set_page_config(page_title=page_title, layout=layout)
    except StreamlitAPIException:
        # The launcher may have already configured the page.
        pass


def _inject_theme_css(theme_mode: str) -> None:
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

            [data-testid="stSidebar"] {{
                background: linear-gradient(180deg, var(--surface) 0%, var(--surface-soft) 100%);
                border-right: 1px solid var(--border);
            }}

            .block-container {{
                padding-top: 1.2rem;
                padding-bottom: 2rem;
                max-width: 1200px;
            }}

            .page-hero {{
                background: linear-gradient(135deg, var(--surface) 0%, var(--surface-soft) 100%);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 0.9rem 1.1rem;
                box-shadow: 0 10px 24px var(--shadow);
                margin-bottom: 0.9rem;
            }}

            .page-hero h2 {{
                margin: 0;
                color: var(--text);
                font-size: clamp(1.2rem, 1.8vw, 1.65rem);
            }}

            .page-hero p {{
                margin: 0.35rem 0 0;
                color: var(--muted);
                font-size: 0.92rem;
            }}

            [data-testid="stCodeBlock"] pre,
            [data-testid="stCode"] pre {{
                background: var(--code-bg) !important;
                border: 1px solid var(--border) !important;
                border-radius: 12px !important;
            }}

            .stButton > button,
            .stDownloadButton > button {{
                border-radius: 10px;
                border: 1px solid transparent;
            }}

            .stAlert {{
                border-radius: 12px;
                border: 1px solid var(--border);
            }}

            @media (max-width: 840px) {{
                .block-container {{
                    padding-top: 0.8rem;
                    padding-left: 0.8rem;
                    padding-right: 0.8rem;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def apply_page_theme(
    title: str,
    subtitle: str,
    *,
    layout: str = "wide",
    toggle_key: str = "global_theme_toggle",
) -> None:
    """Apply a consistent page header and shared light/dark app theming."""
    set_page_config_once(page_title=title, layout=layout)

    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "light"

    hero_col, toggle_col = st.columns([5, 1])
    with hero_col:
        st.markdown(
            f"""
            <div class="page-hero">
                <h2>{title}</h2>
                <p>{subtitle}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with toggle_col:
        is_dark = st.toggle(
            "Dark mode",
            value=st.session_state.theme_mode == "dark",
            key=toggle_key,
            help="Switch between light and dark visual themes.",
        )
        st.session_state.theme_mode = "dark" if is_dark else "light"

    _inject_theme_css(st.session_state.theme_mode)
