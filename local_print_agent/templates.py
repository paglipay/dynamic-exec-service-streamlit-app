"""templates.py — Persists named label field-value presets ("templates")
to a JSON file next to this script, same load/save pattern as
agent_config.py.

Each template is a plain dict:
{"name": str, "camera_number": str, "serial_number": str,
 "model_number": str, "site_name": str, "loc_code": str, "copies": int}

Gitignored (see local_print_agent/.gitignore) — like agent_config.json,
this is local test data a tech builds up on their own machine, not
something to ship/share via git.
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATES_PATH = Path(__file__).resolve().parent / "label_templates.json"


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
