"""templates.py — Persists named label field-value presets ("templates")
to a JSON file next to this script, same load/save pattern as
agent_config.py.

Each template is a plain dict:
{"name": str, "camera_number": str, "serial_number": str,
 "model_number": str, "site_name": str, "loc_code": str, "copies": int,
 "include": bool}

A field can contain placeholders -- {camera_number}, {serial_number},
{model_number}, {site_name}, {loc_code} -- substituted at print time via
apply_placeholders() from whatever real values are available then (the
Label fields section for a manual trigger, a broker job's real scan data
for Live Mode) — see print_agent.py's _print_templates. "include" gates
whether a template fires from "🖨️ Print Included" and from a real Live
Mode scan; missing on an older saved template (from before this field
existed) defaults to True everywhere it's read, so nothing already saved
silently stops firing.

Gitignored (see local_print_agent/.gitignore) — like agent_config.json,
this is local test data a tech builds up on their own machine, not
something to ship/share via git.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TEMPLATES_PATH = Path(__file__).resolve().parent / "label_templates.json"

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def apply_placeholders(text: str, values: dict) -> str:
    """Replaces {key} tokens in `text` with values[key]. A token with no
    matching key (a typo, or a key this call site doesn't provide) is left
    as literal text rather than raising or silently blanking it -- so a
    mistake is visible on the printed label instead of vanishing."""
    def repl(m: "re.Match[str]") -> str:
        key = m.group(1)
        return str(values[key]) if key in values else m.group(0)

    return _PLACEHOLDER_RE.sub(repl, text or "")


def load() -> list[dict]:
    if not TEMPLATES_PATH.exists():
        return []
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save(templates: list[dict]) -> None:
    TEMPLATES_PATH.write_text(json.dumps(templates, indent=2), encoding="utf-8")
