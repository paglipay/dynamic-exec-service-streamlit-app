"""broker.py — HTTP client for the print-job broker (slack-to-onedrive-
sync's /print-jobs endpoints; see that repo's app.py + sync_lib.py
"Camera-label print queue" section).

REST + polling, not WebSocket — matches that service's existing job
pattern (/sync+/status, /backfill+/backfill/status) rather than adding
infrastructure it doesn't have. This agent polls GET /print-jobs/pending
on an interval and POSTs .../ack once a job is printed.

Auth: DEVICE_TOKEN (a field-device secret, same one the site-cam PWA
uses there) — separate from TRIGGER_SECRET, which only the Streamlit
app's enqueue side uses.
"""

from __future__ import annotations

import requests


class BrokerError(Exception):
    pass


def list_pending(broker_url: str, device_token: str, device_id: str, device_name: str,
                  timeout: float = 10.0) -> list[dict]:
    """Only returns jobs queued for this device_id — this call also
    doubles as this device's heartbeat (see sync_lib.checkin_device),
    registering/refreshing it for the Streamlit app's device picker."""
    resp = requests.get(
        f"{broker_url.rstrip('/')}/print-jobs/pending",
        headers={"Authorization": f"Bearer {device_token}"},
        params={"device_id": device_id, "device_name": device_name},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise BrokerError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json().get("items", [])


def ack(broker_url: str, device_token: str, job_id: str, device_id: str, timeout: float = 10.0) -> bool:
    resp = requests.post(
        f"{broker_url.rstrip('/')}/print-jobs/{job_id}/ack",
        headers={"Authorization": f"Bearer {device_token}"},
        params={"device_id": device_id},
        timeout=timeout,
    )
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False  # already acked elsewhere, or unknown id — not fatal
    raise BrokerError(f"HTTP {resp.status_code}: {resp.text[:300]}")
