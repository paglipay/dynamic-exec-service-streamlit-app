import json
import os
from typing import Any

import streamlit as st

try:
    import streamlit_authenticator as stauth
except ImportError:  # pragma: no cover - depends on runtime installation
    stauth = None


AUTH_ENABLED_SETTING = "STREAMLIT_AUTH_ENABLED"
CREDENTIALS_SETTING = "STREAMLIT_AUTH_CREDENTIALS_JSON"
USERS_SETTING = "STREAMLIT_AUTH_USERS_JSON"
COOKIE_NAME_SETTING = "STREAMLIT_AUTH_COOKIE_NAME"
COOKIE_KEY_SETTING = "STREAMLIT_AUTH_COOKIE_KEY"
COOKIE_EXPIRY_SETTING = "STREAMLIT_AUTH_COOKIE_EXPIRY_DAYS"


def _get_setting(name: str, default: Any = None) -> Any:
    env_value = os.getenv(name)
    if env_value is not None and str(env_value).strip():
        return env_value

    try:
        secret_value = st.secrets.get(name, default)
        if secret_value is not None and str(secret_value).strip():
            return secret_value
    except Exception:
        pass

    return default


def _get_bool_setting(name: str, default: bool) -> bool:
    raw_value = _get_setting(name)
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _load_json_setting(name: str) -> Any:
    raw_value = _get_setting(name)
    if raw_value is None:
        return None
    if isinstance(raw_value, (dict, list)):
        return raw_value
    return json.loads(str(raw_value))


def _build_credentials() -> dict[str, Any]:
    credentials = _load_json_setting(CREDENTIALS_SETTING)
    if isinstance(credentials, dict) and "usernames" in credentials:
        return credentials

    users = _load_json_setting(USERS_SETTING)
    if isinstance(users, list):
        usernames: dict[str, dict[str, Any]] = {}
        for user in users:
            if not isinstance(user, dict):
                raise ValueError(f"{USERS_SETTING} must contain objects.")
            username = str(user.get("username", "")).strip()
            name = str(user.get("name", username)).strip()
            password = str(user.get("password", "")).strip()
            if not username or not password:
                raise ValueError("Each auth user must include username and hashed password.")

            user_entry: dict[str, Any] = {
                "name": name or username,
                "password": password,
            }
            if user.get("email"):
                user_entry["email"] = user["email"]
            if user.get("roles"):
                user_entry["roles"] = user["roles"]
            usernames[username] = user_entry
        return {"usernames": usernames}

    raise ValueError(
        "Authentication is enabled but no credentials are configured. "
        f"Set {CREDENTIALS_SETTING} with a credentials object or {USERS_SETTING} with a user list."
    )


def _build_authenticator(credentials: dict[str, Any]):
    if stauth is None:
        raise RuntimeError(
            "streamlit-authenticator is not installed. Add it to requirements.txt before enabling auth."
        )

    cookie_name = str(_get_setting(COOKIE_NAME_SETTING, "streamlit_auth")).strip()
    cookie_key = str(_get_setting(COOKIE_KEY_SETTING, "")).strip()
    if not cookie_key:
        raise ValueError(
            f"Authentication is enabled but {COOKIE_KEY_SETTING} is not configured."
        )

    expiry_raw = _get_setting(COOKIE_EXPIRY_SETTING, 7)
    cookie_expiry_days = float(expiry_raw)

    try:
        return stauth.Authenticate(
            credentials=credentials,
            cookie_name=cookie_name,
            cookie_key=cookie_key,
            cookie_expiry_days=cookie_expiry_days,
        )
    except TypeError:
        return stauth.Authenticate(
            credentials,
            cookie_name,
            cookie_key,
            cookie_expiry_days,
        )


def _run_login(authenticator) -> tuple[str | None, bool | None, str | None]:
    attempts = [
        lambda: authenticator.login(location="main"),
        lambda: authenticator.login("Login", "main"),
        lambda: authenticator.login(location="main", fields={"Form name": "Login", "Username": "Username", "Password": "Password", "Login": "Log in"}),
    ]

    last_error = None
    for attempt in attempts:
        try:
            result = attempt()
            if isinstance(result, tuple) and len(result) == 3:
                return result
            if isinstance(result, dict):
                return (
                    result.get("name"),
                    result.get("authentication_status"),
                    result.get("username"),
                )
        except TypeError as exc:
            last_error = exc
            continue

    raise RuntimeError(f"Unsupported streamlit-authenticator login API: {last_error}")


def _render_logout(authenticator) -> None:
    attempts = [
        lambda: authenticator.logout("Logout", "sidebar"),
        lambda: authenticator.logout(location="sidebar"),
        lambda: authenticator.logout("Logout", "main"),
    ]
    for attempt in attempts:
        try:
            attempt()
            return
        except TypeError:
            continue


def require_authentication(page_name: str, required_roles: list[str] | None = None) -> None:
    if not _get_bool_setting(AUTH_ENABLED_SETTING, True):
        return

    try:
        credentials = _build_credentials()
        authenticator = _build_authenticator(credentials)
        name, authentication_status, username = _run_login(authenticator)
    except Exception as exc:
        st.error(f"Authentication setup error: {exc}")
        st.info(
            "Configure auth with environment variables or Streamlit secrets: "
            f"{CREDENTIALS_SETTING} or {USERS_SETTING}, plus {COOKIE_KEY_SETTING}."
        )
        st.stop()

    if authentication_status is None:
        st.warning(f"Please log in to access {page_name}.")
        st.stop()

    if authentication_status is False:
        st.error("Username/password is incorrect.")
        st.stop()

    user_record = credentials.get("usernames", {}).get(username or "", {})
    user_roles = user_record.get("roles", []) or []
    if required_roles and not set(required_roles).intersection(user_roles):
        st.error("You are logged in but do not have access to this page.")
        _render_logout(authenticator)
        st.stop()

    st.session_state["auth_name"] = name
    st.session_state["auth_username"] = username
    st.session_state["auth_roles"] = user_roles

    with st.sidebar:
        st.caption(f"Signed in as {name or username}")
        _render_logout(authenticator)
