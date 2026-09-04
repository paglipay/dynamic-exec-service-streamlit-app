"""agent_config.py — Persists this agent's local settings (broker URL,
device token, poll interval) to a JSON file next to this script.

Gitignored (see local_print_agent/.gitignore) — agent_config.json holds
a live DEVICE_TOKEN once you fill it in via the GUI, so it must never be
committed.
"""

from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "agent_config.json"

DEFAULTS = {
    "broker_url": "",
    "device_token": "",
    "poll_interval_seconds": 5,
    "device_id": "",    # generated once on first load(), then persisted
    "device_name": "",  # defaults to this PC's hostname, editable in the GUI
}


def load() -> dict:
    if not CONFIG_PATH.exists():
        config = dict(DEFAULTS)
    else:
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        config = dict(DEFAULTS)
        config.update({k: v for k, v in data.items() if k in DEFAULTS})

    # device_id identifies this agent to the broker for print-job routing
    # (see sync_lib.py's "Camera-label print queue" section) — it must
    # stay stable across restarts, so generate it once and persist
    # immediately rather than regenerating it in memory every launch.
    changed = False
    if not config["device_id"]:
        config["device_id"] = uuid.uuid4().hex
        changed = True
    if not config["device_name"]:
        try:
            config["device_name"] = socket.gethostname()
        except Exception:
            config["device_name"] = config["device_id"][:8]
        changed = True
    if changed:
        save(config)

    return config


def save(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
