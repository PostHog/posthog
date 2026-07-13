"""Fire-and-forget PostHog capture over plain HTTP (no SDK dependency)."""

import os
import json
import urllib.request

_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")


def capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    api_key = os.environ.get("POSTHOG_API_KEY", "")
    if not api_key:
        return
    payload = json.dumps(
        {"api_key": api_key, "event": event, "distinct_id": distinct_id, "properties": properties or {}}
    ).encode()
    request = urllib.request.Request(f"{_HOST}/i/v0/e/", data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=2)
    except OSError:
        pass  # Analytics must never take the request path down
