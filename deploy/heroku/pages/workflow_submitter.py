"""Workflow Submitter — pick a JSON template and POST it to /workflow or /execute.

Supports two run modes:
  - sync:               POST /workflow (or /execute) and wait for the response.
  - async (live log):   POST /workflow/async, then poll /workflow/job/<id>
                        every second and stream the log into a code block.
"""

from __future__ import annotations

import json
import os
import time

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


CATALOG_MODULE = "plugins.system_tools.json_catalog_plugin"
CATALOG_CLASS = "JsonCatalogPlugin"
DEFAULT_API_BASE = (os.getenv("API_BASE_URL", "") or "").rstrip("/")
ENDPOINT_TO_CATEGORY = {"/workflow": "workflows", "/execute": "execute"}
POLL_INTERVAL_SECONDS = 1.0
MAX_POLL_SECONDS = 600  # 10 minutes — safety cap on the live-log loop


def _post_execute(api_base, method, args, ctor=None):
    """Call /execute on the service to invoke a JsonCatalogPlugin method."""
    payload = {
        "module": CATALOG_MODULE,
        "class": CATALOG_CLASS,
        "method": method,
        "constructor_args": ctor or {},
        "args": args,
    }
    url = f"{api_base.rstrip('/')}/execute"
    resp = requests.post(url, json=payload, timeout=15)

    try:
        body = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:300].replace("\n", " ")
        raise RuntimeError(
            f"HTTP {resp.status_code} from {url} did not return JSON. Body starts with: {snippet!r}"
        )

    if not isinstance(body, dict):
        snippet = repr(body)[:300]
        raise RuntimeError(
            f"HTTP {resp.status_code} from {url} returned non-object JSON: {snippet}"
        )

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
def _list_templates(api_base, category, recursive):
    result = _post_execute(api_base, "list_templates",
                           [{"category": category, "recursive": recursive}])
    return result.get("templates", []) or []


def _read_template(api_base, category, name):
    result = _post_execute(api_base, "read_template",
                           [{"category": category, "name": name}])
    return result.get("content", {}) or {}


def _render_workflow_results(body):
    st.subheader("Step results")
    results = body.get("results") or []
    if not results:
        st.info("No per-step results in response.")
        return
    rows = [{"id": r.get("id", ""), "status": r.get("status", ""),
             "message": r.get("message", "") or ""} for r in results]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    with st.expander("Raw step results", expanded=False):
        st.json(results)


def _run_async_with_live_log(api_base, payload):
    """POST /workflow/async, poll /workflow/job/<id>, stream log lines live."""
    base = api_base.rstrip("/")

    try:
        kickoff = requests.post(f"{base}/workflow/async", json=payload, timeout=15)
    except requests.RequestException as exc:
        st.error(f"Failed to kick off async workflow: {exc}")
        return None
    if kickoff.status_code != 202:
        st.error(f"Service rejected /workflow/async ({kickoff.status_code}): {kickoff.text[:300]}")
        return None
    try:
        kbody = kickoff.json()
    except ValueError:
        st.error("Service did not return JSON from /workflow/async.")
        return None
    job_id = kbody.get("job_id")
    if not job_id:
        st.error(f"No job_id in /workflow/async response: {kbody}")
        return None

    st.info(f"Job started: `{job_id}` — polling every {POLL_INTERVAL_SECONDS:.0f}s")

    status_placeholder = st.empty()
    log_container = st.container(height=350)
    log_placeholder = log_container.empty()

    started = time.monotonic()
    last_log_lines = -1
    final_job = None

    while True:
        try:
            poll = requests.get(f"{base}/workflow/job/{job_id}", timeout=15)
            poll.raise_for_status()
            job = poll.json()
        except requests.RequestException as exc:
            st.error(f"Polling failed: {exc}")
            return None

        log_lines = job.get("log") or []
        status = job.get("status", "unknown")

        if len(log_lines) != last_log_lines:
            log_text = "\n".join(log_lines) if log_lines else "(no log lines yet)"
            log_placeholder.code(log_text, language="text")
            last_log_lines = len(log_lines)

        elapsed = time.monotonic() - started
        status_placeholder.write(
            f"**status:** `{status}`  ·  **lines:** {len(log_lines)}  ·  **elapsed:** {elapsed:.0f}s"
        )

        if status != "running":
            final_job = job
            break

        if elapsed > MAX_POLL_SECONDS:
            st.warning(f"Polling stopped after {MAX_POLL_SECONDS}s. Job is still running on the server.")
            return None

        time.sleep(POLL_INTERVAL_SECONDS)

    return final_job


# ----- Connection -----
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

run_mode = st.radio(
    "Run mode",
    options=["sync", "async (live log)"],
    horizontal=True,
    help=(
        "**sync** waits for the response. **async** posts to /workflow/async, polls "
        "/workflow/job/<id>, and streams the log live. Async only applies to /workflow."
    ),
)
async_mode = run_mode.startswith("async") and endpoint == "/workflow"
if run_mode.startswith("async") and endpoint == "/execute":
    st.caption("⚠️ async mode only applies to `/workflow`; `/execute` will run sync.")

if not api_base:
    st.warning("Set the Service URL above (or set `API_BASE_URL` in the environment) to load templates.")
    st.stop()

category = ENDPOINT_TO_CATEGORY[endpoint]
recursive = endpoint == "/execute"

# ----- Template selection -----
st.subheader("Template")
left, right = st.columns([3, 1])
with right:
    if st.button("🔄 Reload list", help="Bust the 30s cache and re-fetch from the service"):
        _list_templates.clear()

try:
    templates = _list_templates(api_base, category, recursive)
except requests.RequestException as exc:
    st.error(f"Could not reach service: {exc}")
    st.stop()
except Exception as exc:
    st.error(f"Failed to list templates: {exc}")
    st.stop()

if not templates:
    st.info(f"No templates found in category '{category}'.")
    st.stop()

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

if recursive and "/" in chosen_rel:
    subdir, leaf = chosen_rel.rsplit("/", 1)
else:
    subdir, leaf = "", chosen_rel

# ----- Load template content -----
content_key = f"workflow_submitter_content::{endpoint}::{chosen_rel}"
load_key = f"workflow_submitter_loaded::{endpoint}::{chosen_rel}"

if not st.session_state.get(load_key):
    try:
        if subdir:
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

# ----- Edit & submit -----
st.subheader("Edit & submit")
edited_text = st.text_area(
    "JSON payload",
    value=st.session_state.get(content_key, ""),
    height=420,
    key=f"workflow_submitter_textarea::{endpoint}::{chosen_rel}",
    help="Tweak any field before submitting (paths, filters, etc.).",
)

submit_label = (
    f"🚀 Submit to {endpoint} (async)" if async_mode else f"🚀 Submit to {endpoint}"
)
col_submit, col_dry = st.columns([1, 1])
with col_submit:
    submit_clicked = st.button(submit_label, type="primary", use_container_width=True)
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

    if async_mode:
        st.subheader("Live log")
        job = _run_async_with_live_log(api_base, payload)
        if job is None:
            st.stop()

        st.write(f"**final status:** `{job.get('status')}`")
        if job.get("status") == "done":
            body = job.get("result") or {}
            _render_workflow_results(body)
            with st.expander("Full /workflow response", expanded=False):
                st.json(body)
        else:
            err = job.get("error") or "(no error message)"
            st.error(f"Job failed: {err}")
            with st.expander("Full job state", expanded=False):
                st.json(job)
    else:
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
            st.error(f"status: {top_status} - {body.get('message', '')}")

        if endpoint == "/workflow":
            _render_workflow_results(body)
            with st.expander("Full /workflow response", expanded=False):
                st.json(body)
        else:
            with st.expander("Full /execute response", expanded=True):
                st.json(body)
