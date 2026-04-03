"""
Contractor Tool Kit – shared branding helpers.
Call apply_branding() at the top of any page to inject CSS + sidebar identity.
"""
import streamlit as st

BRAND_NAME = "Contractor Tool Kit"
BRAND_TAGLINE = "Built for the trades"
BRAND_ICON = "🔧"


def inject_brand_css() -> None:
    st.markdown(
        """
        <style>
        /* ── Sidebar dark background ── */
        [data-testid="stSidebar"] > div:first-child {
            background-color: #1C1C1E;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] li,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #F0F0F0 !important;
        }
        [data-testid="stSidebar"] a {
            color: #E87722 !important;
        }
        [data-testid="stSidebar"] hr {
            border-color: #333 !important;
        }

        /* ── Brand strip ── */
        .ctk-brand {
            background: linear-gradient(90deg, #E87722 0%, #C45E00 100%);
            padding: 14px 18px 12px;
            border-radius: 10px;
            margin-bottom: 4px;
        }
        .ctk-brand-title {
            font-size: 1.1rem;
            font-weight: 800;
            color: #ffffff;
            letter-spacing: 0.4px;
            margin: 0 0 3px 0;
        }
        .ctk-brand-tagline {
            font-size: 0.70rem;
            color: rgba(255,255,255,0.82);
            margin: 0;
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        /* ── Card grid section labels ── */
        .ctk-section {
            font-size: 0.68rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: #999;
            padding: 18px 0 6px 2px;
        }

        /* ── Sidebar buttons (e.g. Logout) — visible on dark bg ── */
        [data-testid="stSidebar"] .stButton > button {
            background: transparent !important;
            border: 1.5px solid #E87722 !important;
            color: #E87722 !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            padding: 6px 14px !important;
            border-radius: 8px !important;
            line-height: 1.4 !important;
            transition: background 0.15s, color 0.15s !important;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: #E87722 !important;
            color: #ffffff !important;
            border-color: #E87722 !important;
        }
        [data-testid="stSidebar"] .stButton > button:focus,
        [data-testid="stSidebar"] .stButton > button:active {
            background: #C45E00 !important;
            color: #ffffff !important;
            border-color: #C45E00 !important;
            box-shadow: 0 0 0 2px rgba(232,119,34,0.35) !important;
        }

        /* ── Button card style (main area only) ── */
        .stButton > button {
            border-radius: 10px !important;
            border: 1.5px solid #E0E0DA !important;
            background: #FAFAF7 !important;
            font-weight: 600 !important;
            font-size: 0.82rem !important;
            padding: 14px 8px !important;
            line-height: 1.4 !important;
            transition: border-color 0.15s, background 0.15s, color 0.15s !important;
            color: #1C1C1E !important;
        }
        .stButton > button:hover {
            border-color: #E87722 !important;
            background: #FFF4EC !important;
            color: #C45E00 !important;
        }
        .stButton > button:focus,
        .stButton > button:active {
            border-color: #C45E00 !important;
            background: #FFE8D2 !important;
            color: #B04A00 !important;
            box-shadow: 0 0 0 2px rgba(232,119,34,0.25) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    st.sidebar.markdown(
        f"""
        <div class="ctk-brand">
            <p class="ctk-brand-title">{BRAND_ICON}&nbsp;{BRAND_NAME}</p>
            <p class="ctk-brand-tagline">{BRAND_TAGLINE}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.divider()

    # Show signed-in user and logout (rendered once per cycle since
    # apply_branding() is only called from main.py).
    _auth_username = st.session_state.get("auth_username")
    if _auth_username:
        _auth_name = st.session_state.get("auth_name") or _auth_username
        st.sidebar.caption(f"Signed in as **{_auth_name}**")
        if st.sidebar.button("Logout", key="_ctk_logout_btn"):
            # Call the authenticator's logout to expire the persistent cookie.
            # Without this, the cookie re-authenticates the user on next load.
            _authenticator = st.session_state.get("_ctk_authenticator")
            if _authenticator is not None:
                try:
                    _authenticator.logout()
                except Exception:
                    try:
                        _authenticator.logout("Logout", "main")
                    except Exception:
                        pass
            for _k in ("auth_name", "auth_username", "auth_roles",
                       "name", "username", "authentication_status",
                       "_ctk_authenticator"):
                st.session_state.pop(_k, None)
            st.rerun()


def apply_branding() -> None:
    inject_brand_css()
    render_sidebar_brand()


def render_footer() -> None:
    """Persistent footer strip — call once from the home screen."""
    st.markdown(
        """
        <style>
        .ctk-footer {
            margin-top: 48px;
            padding: 18px 0 8px;
            border-top: 1px solid #E0E0DA;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
        }
        .ctk-footer-copy {
            font-size: 0.75rem;
            color: #AAA;
        }
        .ctk-footer-links {
            display: flex;
            gap: 20px;
        }
        .ctk-footer-links a {
            font-size: 0.78rem;
            font-weight: 600;
            color: #E87722;
            text-decoration: none;
            letter-spacing: 0.2px;
        }
        .ctk-footer-links a:hover { text-decoration: underline; }
        </style>
        <div class="ctk-footer">
            <span class="ctk-footer-copy">© 2026 Contractor Tool Kit · Built for the trades</span>
            <div class="ctk-footer-links">
                <a href="?contact=ticket">🎫 Support</a>
                <a href="?contact=sales">💼 Contact Sales</a>
                <a href="?contact=help">📚 Help Center</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
