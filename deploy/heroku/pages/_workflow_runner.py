"""
_workflow_runner.py — Linear (Next/Prev) wizard that stitches existing
pages together.

main.py is responsible for:
  - Discovering workflow folders under deploy/heroku/workflows/
  - Rendering a card per workflow in the catalog
  - Setting st.session_state["selected_workflow"] = <folder_slug> when a
    workflow card is clicked
  - Importing this file (via importlib.spec_from_file_location, same as
    every other page) so this script executes at module-load time.

This script reads the slug from session_state, loads
  workflows/<slug>/workflow.yaml,
and renders the active step:
  1. Workflow title + description
  2. A locked-down nav header (Step N of M + Prev/Next buttons), fixed
     to the top of the viewport so it stays visible as you scroll
     through a long step's content — see _sticky_header_css()'s
     docstring for how (position: fixed, not sticky — sticky doesn't
     work inside Streamlit's own container nesting; verified).
  3. Step instructions (markdown file or inline `markdown:` key)
  4. The inner page from pages/<page>.py, executed inline

Steps are independent — each tool keeps its own session_state, so the
user downloads from step N and uploads as input to step N+1 (the
hand-off is documented in each step's instruction markdown).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional

import streamlit as st

try:
    import yaml
except ImportError:
    yaml = None  # surfaced below as a clear error


# ── Layout ────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent                  # .../deploy/heroku/pages
HEROKU_DIR = HERE.parent                                # .../deploy/heroku
PAGES_DIR = HEROKU_DIR / "pages"
WORKFLOWS_DIR = HEROKU_DIR / "workflows"


# ── Spec parsing ──────────────────────────────────────────────────────────────

def _load_workflow_spec(slug: str) -> Optional[dict]:
    """Return the parsed workflow.yaml dict, or None if not loadable."""
    if yaml is None:
        st.error(
            "PyYAML is not installed. Add `PyYAML` to requirements.txt "
            "and redeploy."
        )
        return None

    wdir = WORKFLOWS_DIR / slug
    spec_path = wdir / "workflow.yaml"
    if not spec_path.is_file():
        st.error(f"Workflow spec not found: {spec_path}")
        return None

    try:
        with open(spec_path, "r", encoding="utf-8") as fh:
            spec = yaml.safe_load(fh)
    except Exception as exc:
        st.error(f"Failed to parse {spec_path.name}: {exc}")
        return None

    if not isinstance(spec, dict) or "steps" not in spec:
        st.error(f"{spec_path.name} is missing a top-level `steps:` list.")
        return None

    return spec


def _instructions_text(workflow_dir: Path, step: dict) -> Optional[str]:
    """Return markdown text for this step, from `instructions:` (file path
    relative to the workflow folder) or `markdown:` (inline string)."""
    if "markdown" in step and step["markdown"]:
        return str(step["markdown"])
    file_ref = step.get("instructions")
    if not file_ref:
        return None
    instr_path = workflow_dir / file_ref
    if not instr_path.is_file():
        return f"_(instructions file not found: `{file_ref}`)_"
    try:
        return instr_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"_(could not read instructions: {exc})_"


# ── Sticky nav header ──────────────────────────────────────────────────────────

_STICKY_MARKER_CLASS = "wf-sticky-nav-marker"


def _sticky_header_css() -> None:
    """Injects CSS that pins the step-nav bar to a fixed position at the
    top of the viewport, below Streamlit's own app header.

    position: sticky does NOT work here — tried it first, and verified
    empirically (headless-browser measurement, not just theory) that it
    fails: a st.container()'s own DOM wrapper (stLayoutWrapper) is only
    ever as tall as the container's own content, giving a sticky child
    zero room to "float" within it, so it just scrolls away with
    everything else regardless of which ancestor gets position:sticky.
    position: fixed sidesteps this entirely — it's anchored to the
    viewport, not to any Streamlit-controlled containing block, so it's
    unaffected by that nesting. Confirmed working the same way: measured
    the nav bar's on-screen position before/after a large programmatic
    scroll and confirmed it didn't move.

    `top: 60px` matches Streamlit's own header height, measured the same
    way (header['data-testid=stHeader'].getBoundingClientRect().height
    == 60 in this Streamlit version) — if a future Streamlit version
    changes that height, this offset would need re-measuring.

    Targeting the container: st.container() only gets an auto-generated
    (emotion-hashed) CSS class, no stable name to select by, and a
    selector keyed to DOM position (nth-of-type) would silently target
    the wrong block the moment content above it changes. Instead: an
    invisible <span class="wf-sticky-nav-marker"> is rendered as the
    FIRST element inside the container, and CSS :has() keys the
    selector to that container's *content*, not its position — verified
    against this Streamlit version's actual rendered DOM (a
    st.container()'s st.markdown/st.columns children are siblings under
    one div[data-testid="stVerticalBlock"], so :has() targeting that
    div's stElementContainer child, not a bare div, correctly grabs
    only this one container and not an outer ancestor that also
    happens to have the marker as a deep descendant).
    Requires a browser with CSS :has() support (Chrome/Edge 105+,
    Safari 15.4+, Firefox 121+) — on an older browser this just
    silently isn't fixed in place; the buttons still render and work.
    """
    st.markdown(
        f"""
        <style>
        div[data-testid="stVerticalBlock"]:has(> div.stElementContainer .{_STICKY_MARKER_CLASS}) {{
            position: fixed;
            top: 60px;
            left: 0;
            right: 0;
            z-index: 999;
            background-color: var(--background-color, white);
            padding: 0.5rem 2rem;
            border-bottom: 1px solid rgba(128, 128, 128, 0.3);
        }}
        /* room for the fixed bar so it doesn't cover the content that
        would otherwise render right at the top of the page */
        div[data-testid="stMainBlockContainer"] {{
            padding-top: 5rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_nav_header(step_key: str, current: int, total: int) -> None:
    """The fixed bar itself: step breadcrumb + Prev/Next. Lives inside
    one st.container() so _sticky_header_css()'s :has() selector can
    pin the whole thing as a unit."""
    with st.container():
        st.markdown(f'<span class="{_STICKY_MARKER_CLASS}"></span>', unsafe_allow_html=True)
        col_prev, col_mid, col_next = st.columns([1, 2, 1])

        with col_prev:
            if current > 0:
                if st.button("⬅️ Previous step", use_container_width=True):
                    st.session_state[step_key] = current - 1
                    st.rerun()

        with col_mid:
            st.markdown(
                f"<div style='text-align:center'>Step {current + 1} of {total}</div>",
                unsafe_allow_html=True,
            )

        with col_next:
            if current < total - 1:
                if st.button("Next step ➡️", use_container_width=True, type="primary"):
                    st.session_state[step_key] = current + 1
                    st.rerun()
            else:
                st.success("✅ Final step")


# ── Inner-page execution ──────────────────────────────────────────────────────

def _run_inner_page(page_filename: str, module_tag: str) -> None:
    """Exec the named pages/<page_filename> file inline (same loader
    pattern main.py uses for the regular page view)."""
    page_path = PAGES_DIR / page_filename
    if not page_path.is_file():
        st.error(f"Tool page not found: {page_filename}")
        return

    try:
        # Unique module name per step so previous-step state in
        # sys.modules can't leak into the current step.
        spec = importlib.util.spec_from_file_location(module_tag, page_path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_tag] = mod
        spec.loader.exec_module(mod)
        if hasattr(mod, "app"):
            mod.app()
    except Exception as exc:
        st.error(f"Failed to run `{page_filename}`: {exc}")


# ── Render ────────────────────────────────────────────────────────────────────

def _render() -> None:
    slug = st.session_state.get("selected_workflow")
    if not slug:
        st.error("No workflow selected.")
        return

    spec = _load_workflow_spec(slug)
    if spec is None:
        return

    steps = spec.get("steps") or []
    if not steps:
        st.warning("This workflow has no steps defined.")
        return

    workflow_name = spec.get("name", slug)
    workflow_icon = spec.get("icon", "🧭")
    description = spec.get("description", "")
    workflow_dir = WORKFLOWS_DIR / slug

    # Per-workflow step index, kept in session_state. Resets are handled
    # by main.py when the user exits via "Back to Tool Kit".
    step_key = f"_wf_step_{slug}"
    if step_key not in st.session_state:
        st.session_state[step_key] = 0
    current = max(0, min(int(st.session_state[step_key]), len(steps) - 1))

    step = steps[current] or {}
    step_title = step.get("title", f"Step {current + 1}")
    page_filename = step.get("page")

    # ── Header ────────────────────────────────────────────────────────────────
    st.title(f"{workflow_icon} {workflow_name}")
    if description:
        st.caption(description)

    # Sticky nav: step breadcrumb + Prev/Next, pinned to the top of the
    # scroll area (see _sticky_header_css()'s docstring) so a long
    # step's content never buries navigation at the bottom.
    _sticky_header_css()
    _render_nav_header(step_key, current, len(steps))
    st.markdown(f"**{step_title}**")
    st.progress((current + 1) / len(steps))

    # ── Instructions (left) + inner tool page (right), side-by-side ─────────
    # Narrow instructions column on the left, wide tool column on the right.
    # Streamlit's "wide" layout (set in main.py) gives us enough horizontal
    # space to split 1:3 without cramping most tool pages.
    instr_col, tool_col = st.columns([1, 3], gap="large")

    with instr_col:
        instructions = _instructions_text(workflow_dir, step)
        if instructions:
            st.markdown("### 📋 Instructions")
            st.markdown(instructions)
        else:
            st.caption("_No instructions for this step._")

    with tool_col:
        if not page_filename:
            st.error(f"Step {current + 1} is missing a `page:` filename.")
        else:
            module_tag = f"_wf_{slug}_step_{current}"
            _run_inner_page(page_filename, module_tag)


# Execute on module load (matches the convention of the other pages —
# top-level UI rather than an explicit app() entry point).
_render()
