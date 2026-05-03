"""Workflow Submitter — pick a JSON template and POST it to /workflow or /execute.

Lists available templates by calling /execute with JsonCatalogPlugin.list_templates,
loads the chosen one with JsonCatalogPlugin.read_template, lets the user edit the
JSON, then POSTs to either /workflow or /execute on the dynamic-exec-service.
"""

from __future__ import annotations

import json
import os

import requests
import streamlit as st

from _ai_assistant_panel import render_ai_assistant_panel
from _auth_guard import require_authentication


st.set_page_config(page_title="Workflow Submitter", page_icon="🔁")
require_authentication("Workflow Submitter")
render_ai_assistant_panel("Workflow Submitter")
st.title("🔁 Workflow Submitter")
st.caption(
    "Pick a JSON template from the dynamic-exec-service catalog, edit if needed, "
    "and POST it to /workflow or /execute."
)


# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

CATALOG_MODULE = "plugins.system_tools.json_catalog_plugin"
CATALOG_CLASS = "JsonCatalogPlugin"

DEFAULT_API_BASE = (os.getenv("API_BASE_URL", "") or "").rstrip("/")

# Map endpoint -> catalog category for the catalog plugin.
ENDPOINT_TO_CATEGORY = {
    "/workflow": "workflows",
    "/execute": "execute",
}


def _post_execute(api_base: str, method: str, args: list, ctor: dict | None = None) -> dict:
    """Call /execute on the service to invoke a JsonCatalogPlugin method.

    Raises RuntimeError with a useful diagnostic when the response shape is wrong.
    """
    payload = {
        "module": CATALOG_MODULE,
        "class": CATALOG_CLASS,
        "method": method,
        "constructor_args": ctor or {},
        "args": args,
    }
    url = f"{api_base.rstrip('/')}/execute"
    resp = requests.post(url, json=payload, timeout=15)

    # Try to parse JSON; if it fails, surface the raw text and status.
    try:
        body = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise RuntimeError(
            f"HTTP {resp.status_code} from {url} did not return JSON. Body starts with: {snippet!r}"
        )

    # Some misconfigured proxies / error pages return a top-level string or list.
    if not isinstance(body, dict):
        snippet = repr(body)[:300]
        raise RuntimeError(
            f"HTTP {resp.status_code} from {url} returned non-object JSON: {snippet}"
        )

    # Now safe to call .get on body.
    if resp.status_code >= 400:
        msg = body.get("message") or body.get("error") or f"HTTP {resp.status_code}"
        raise RuntimeError(f"Service error ({resp.status_code}): {msg}")

    if body.get("status") != "success":
        raise RuntimeError(body.get("message") or "Service returned status != 'success'")

    result = body.get("result", {})
    if not isinstance(result, dict):
        raise RuntimeError(f"Service result was not an object: {repr(result)[:200]}")
    return result


@st.cache_data(ttl=30, show_spinner=False)
def _list_templates(api_base: str, category: str, recursive: bool) -> list[dict]:
    result = _post_execute(api_base, "list_templates", [{"category": category, "recursive": recursive}])
    return result.get("templates", []) or []


def _read_template(api_base: str, category: str, name: str) -> dict:
    result = _post_execute(api_base, "read_template", [{"category": category, "name": name}])
    return result.get("content", {}) or {}


def _render_workflow_results(body: dict) -> None:
    st.subheader("Step results")
    results = body.get("results") or []
    if not results:
        st.info("No per-step results in response.")
        return

    rows = []
    for r in results:
        rows.append(
            {
                "id": r.get("id", ""),
                "status": r.get("status", ""),
                "message": r.get("message", "") or "",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Raw step results", expanded=False):
        st.json(results)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

st.subheader("Connection")
col1, col2 = st.columns([3, 2])
with col1:
    api_base = st.text_input(
        "Service URL",
        value=st.session_state.get("workflow_submitter_api_base", DEFAULT_API_BASE),
        placeholder="https://your-flask-app.example.com",
        help="Base URL of the dynamic-exec-service (no trailing slash).",
    ).strip()
    st.session_state["workflow_submitter_api_base"] = api_base
with col2:
    endpoint = st.radio(
        "Endpoint",
        options=list(ENDPOINT_TO_CATEGORY.keys()),
        horizontal=True,
        help="`/workflow` for multi-step pipelines, `/execute` for a single plugin call.",
    )

if not api_base:
    st.warning("Set the Service URL above (or set `API_BASE_URL` in the environment) to load templates.")
    st.stop()

category = ENDPOINT_TO_CATEGORY[endpoint]
recursive = endpoint == "/execute"  # /execute templates live in subdirs by plugin

# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------

st.subheader("Template")
left, right = st.columns([3, 1])
with right:
    if st.button("🔄 Reload list", help="Bust the 30s cache and re-fetch from the service"):
        _list_templates.clear()

try:
    templates = _list_templates(api_base, category, recursive)
except requests.HTTPError as exc:
    st.error(f"Service returned HTTP {exc.response.status_code}: {exc.response.text[:300]}")
    st.stop()
except requests.RequestException as exc:
    st.error(f"Could not reach service: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"Failed to list templates: {exc}")
    st.stop()

if not templates:
    st.info(f"No templates found in category '{category}'.")
    st.stop()

# Each template entry has: name, relative_path, size_bytes, modified_at
options = [t.get("relative_path") or t.get("name") for t in templates]
labels = {
    (t.get("relative_path") or t.get("name")):
        f"{t.get('relative_path') or t.get('name')}  ({t.get('size_bytes', 0)} bytes)"
    for t in templates
}

with left:
    chosen_rel = st.selectbox(
        f"Pick a template ({len(templates)} available)",
        options=options,
        format_func=lambda v: labels.get(v, v),
    )

if not chosen_rel:
    st.stop()

# Convert "subdir/name.json" -> name argument the plugin expects.
# When recursive=False (workflows) this is just the bare name; when recursive=True
# (execute) the relative path includes a subdir, but the catalog plugin's
# read_template() only accepts a flat name. Work around by listing in the same
# subdir and pulling its bare name — for recursive, we re-target the plugin to
# the subdir via a per-call category override below.
if recursive and "/" in chosen_rel:
    subdir, leaf = chosen_rel.rsplit("/", 1)
else:
    subdir, leaf = "", chosen_rel

# ---------------------------------------------------------------------------
# Load template content
# ---------------------------------------------------------------------------

content_key = f"workflow_submitter_content::{endpoint}::{chosen_rel}"
load_key = f"workflow_submitter_loaded::{endpoint}::{chosen_rel}"

if not st.session_state.get(load_key):
    try:
        if subdir:
            # /execute templates in subdirs — point the catalog at the subdir
            # via a per-call category override. The plugin's `name` field
            # disallows path separators, so we cannot pass "subdir/leaf".
            result = _post_execute(
                api_base,
                "read_template",
                [{"category": "_scoped", "name": leaf}],
                ctor={"categories": {"_scoped": f"jsons/system_tools/{subdir}"}},
            )
            content = result.get("content", {})
        else:
            content = _read_template(api_base, category, leaf)
        st.session_state[content_key] = json.dumps(content, indent=2)
        st.session_state[load_key] = True
    except Exception as exc:
        st.error(f"Failed to load template '{chosen_rel}': {exc}")
        st.stop()

st.subheader("Edit & submit")
edited_text = st.text_area(
    "JSON payload",
    value=st.session_state.get(content_key, ""),
    height=420,
    key=f"workflow_submitter_textarea::{endpoint}::{chosen_rel}",
    help="Tweak any field before submitting (paths, filters, etc.).",
)

col_submit, col_dry = st.columns([1, 1])
with col_submit:
    submit_clicked = st.button(f"🚀 Submit to {endpoint}", type="primary", use_container_width=True)
with col_dry:
    if st.button("📋 Validate JSON only", use_container_width=True):
        try:
            json.loads(edited_text)
            st.success("Valid JSON.")
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")

if submit_clicked:
    try:
        payload = json.loads(edited_text)
    except json.JSONDecodeError as exc:
        st.error(f"Invalid JSON: {exc}")
        st.stop()

    target_url = f"{api_base.rstrip('/')}{endpoint}"
    with st.spinner(f"POST {target_url} ..."):
        try:
            resp = requests.post(target_url, json=payload, timeout=120)
        except requests.RequestException as exc:
            st.error(f"Request failed: {exc}")
            st.stop()

    st.write(f"**HTTP status:** `{resp.status_code}`")

    try:
        body = resp.json()
    except ValueError:
        st.error("Service did not return JSON.")
        st.code(resp.text[:2000] or "(empty)")
        st.stop()

    top_status = body.get("status", "unknown")
    if top_status == "success":
        st.success(f"status: {top_status}")
    else:
        st.error(f"status: {top_status} — {body.get('message', '')}")

    if endpoint == "/workflow":
        _render_workflow_results(body)
        with st.expander("Full /workflow response", expanded=False):
            st.json(body)
    else:
        with st.expander("Full /execute response", expanded=True):
            st.json(body)
    except ValueError:
        st.error("Service did not return JSON.")
        st.code(resp.text[:2000] or "(empty)")
        st.stop()

    top_status = body.get("status", "unknown")
    if top_status == "success":
        st.success(f"status: {top_status}")
    else:
        st.error(f"status: {top_status} - {body.get('message', '')}")

    if endpoint == "/workflow":
        _render_workflow_results(body)
        with st.expander("Full /workflow response", expanded=False):
            st.json(body)
    else:
        with st.expander("Full /execute response", expanded=True):
            st.json(body)
)
