"""agent_config.py — Persists this agent's local settings (broker URL,
device token, poll interval) to a JSON file next to this script.

Gitignored (see local_print_agent/.gitignore) — agent_config.json holds
a live DEVICE_TOKEN once you fill it in via the GUI, so it must never be
committed.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "agent_config.json"

DEFAULTS = {
    "broker_url": "",
    "device_token": "",
    "poll_interval_seconds": 5,
}


def load() -> dict:
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
