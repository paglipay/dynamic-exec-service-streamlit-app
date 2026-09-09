"""templates.py — Persists named label field-value presets ("templates")
to a JSON file next to this script, same load/save pattern as
agent_config.py.

Each template is a plain dict:
{"name": str, "camera_number": str, "serial_number": str,
 "model_number": str, "site_name": str, "loc_code": str, "ip_address": str,
 "copies": int, "include": bool}

A field can contain placeholders, substituted at print time via
apply_placeholders() from whatever real values are available then (the
Label fields section for a manual trigger, a broker job's real scan data
for Live Mode) — see print_agent.py's _print_templates. The base tokens
are the LabelData fields themselves: {camera_number} {serial_number}
{model_number} {site_name} {loc_code} {ip_address}. build_placeholder_values()
below adds two derived ones on top of whatever raw fields it's given:
  {location_code}  -- alias for {loc_code}, the more natural spelling
  {serial_last4}   -- just the last 4 characters of {serial_number}, e.g.
                       for a compact tag, or folded into a combined field
                       (see the "Loc + Camera # Combo" sample template)
"include" gates whether a template fires from "🖨️ Print Included" and
from a real Live Mode scan; missing on an older saved template (from
before this field existed) defaults to True everywhere it's read, so
nothing already saved silently stops firing.

An optional "layout" key -- a list of freely-positioned text elements,
each {"text", "x", "y", "font_size", "align", "bold"} -- overrides the
classic fixed camera#/model/serial bands entirely when present and
non-empty (see label.py's render_label_custom and print_agent.py's
"🎨 Edit Layout"). Absent/empty means "use the classic fixed layout",
which is every template that predates this feature.

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


def build_placeholder_values(raw: dict) -> dict:
    """Expands a raw field dict (camera_number, serial_number, model_number,
    site_name, loc_code, ip_address) with the two derived/aliased tokens
    documented at the top of this file, for apply_placeholders."""
    values = dict(raw)
    values.setdefault("location_code", values.get("loc_code", ""))
    serial = values.get("serial_number") or ""
    values.setdefault("serial_last4", serial[-4:])
    return values


# Seeded only when label_templates.json has never existed on this machine
# (see load() below) -- illustrates the placeholder system for a tech
# opening this for the first time, same spirit as agent_config.py
# generating a device_id/device_name on first load. Both start unchecked
# (include: False) so they never fire on this tech's very next real scan
# just because they exist -- toggle Include once you've looked them over.
DEFAULT_TEMPLATES: list[dict] = [
    {
        "name": "Loc + Camera # Combo",
        "camera_number": "{loc_code}_{camera_number}",  # e.g. "8895_CAM01"
        "serial_number": "{serial_number}",
        "model_number": "{model_number}",
        "site_name": "{site_name}",
        "loc_code": "{loc_code}",
        "ip_address": "{ip_address}",
        "copies": 1,
        "include": False,
    },
    {
        "name": "Compact Serial (Last 4)",
        "camera_number": "{camera_number}",
        "serial_number": "{serial_last4}",  # e.g. "9745" from "B8A44F9C9745"
        "model_number": "{model_number}",
        "site_name": "{site_name}",
        "loc_code": "{loc_code}",
        "ip_address": "",
        "copies": 2,
        "include": False,
    },
]


def load() -> list[dict]:
    if not TEMPLATES_PATH.exists():
        return [dict(t) for t in DEFAULT_TEMPLATES]  # copies -- callers mutate their own list freely
    try:
        data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save(templates: list[dict]) -> None:
    TEMPLATES_PATH.write_text(json.dumps(templates, indent=2), encoding="utf-8")
