import os
import json
import urllib.request


def capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    """Send a PostHog capture event. No-op unless POSTHOG_API_KEY is set."""
    api_key = os.environ.get("POSTHOG_API_KEY")
    if not api_key:
        return
    host = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
    payload = {
        "api_key": api_key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": properties or {},
    }
    request = urllib.request.Request(
        f"{host}/i/v0/e/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=2)
    except OSError:
        pass  # analytics must never break report generation
