"""Decode rrweb network-plugin events out of a recording's snapshot blocks.

Network requests never reach ClickHouse. posthog-js captures them as rrweb plugin events that travel
inside the snapshot blobs, so the only way to read them server-side is to decode the blocks. The scanner
needs them because a failed request and a slow one look the same on video: both show a spinner.

A leaf module, so the activity and the tool can both import it without touching `types.py`, which
participates in an import cycle with the `scanners` package.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

# The two plugin names that carry network data. posthog-js emits `posthog/network@1` with the fields
# index-encoded as numeric string keys; rrweb's own recorder emits `rrweb/network@1` with named keys and
# several requests per event. A recording normally holds one or the other.
POSTHOG_NETWORK_PLUGIN = "posthog/network@1"
RRWEB_NETWORK_PLUGIN = "rrweb/network@1"

_PLUGIN_EVENT_TYPE = 6

# Index-encoded field positions in a `posthog/network@1` payload, mirroring
# `PerformanceEventReverseMapping` in frontend/src/scenes/session-recordings/apm/performance-event-utils.ts.
# Only the fields the scanner reads are listed; the full mapping runs to 40 entries.
_INDEXED_FIELDS: dict[str, str] = {
    "0": "entry_type",
    "2": "name",
    "18": "initiator_type",
    "21": "response_status",
    "39": "duration",
}

# Named fields in an `rrweb/network@1` captured request. `status` and `responseStatus` both land on
# `response_status`: the performance observer supplies one and wrapped fetch/xhr the other. `status` is
# listed second so it wins when a request carries both, matching the frontend's preference.
_NAMED_FIELDS: dict[str, str] = {
    "entryType": "entry_type",
    "name": "name",
    "initiatorType": "initiator_type",
    "method": "method",
    "duration": "duration",
    "responseStatus": "response_status",
    "status": "response_status",
}

# A request slower than this is worth showing even when it succeeded, because it is what a user reads as a
# hang. Below it a successful request explains nothing the video does not already show.
SLOW_REQUEST_MS = 1000

# Per-session cap. A busy page issues thousands of requests; the scanner only ever reads a few windows of
# them, and the payload rides through Redis.
MAX_REQUESTS_PER_SESSION = 500

_MAX_URL_LENGTH = 200


class NetworkRequest(BaseModel, frozen=True):
    """One captured request the scanner may be shown.

    `timestamp_ms` stays absolute (epoch milliseconds) because this payload is built without session
    metadata. It is converted to a recording-relative `rec_t` when the tool index is built, against the
    same recording-start anchor the video footer and the events tool use.
    """

    timestamp_ms: int
    url: str
    method: str | None = None
    status: int | None = None
    duration_ms: int | None = None
    initiator: str | None = None


class SessionNetworkPayload(BaseModel, frozen=True):
    """The network requests worth showing for one session, stashed in Redis between activities."""

    requests: list[NetworkRequest] = Field(default_factory=list)
    # False when the recording holds no network plugin events at all, which means the SDK never captured
    # them. The prompt has to tell those apart: with capture off, an empty result says nothing about
    # whether requests failed, and the model must not read it as "nothing failed".
    captured: bool = False
    # True when the session produced more interesting requests than `MAX_REQUESTS_PER_SESSION`.
    truncated: bool = False


def parse_network_payload(lines: Iterable[str]) -> SessionNetworkPayload:
    """Decode every snapshot line and keep the requests a scanner can act on.

    Each line is one JSON object, `{"window_id": ..., "data": [event, ...]}`. Lines that don't parse are
    skipped rather than raised on: a single corrupt block must not lose a scan the rest of the session.
    """
    captured = False
    kept: list[NetworkRequest] = []
    truncated = False

    for raw_request, timestamp_ms in _iter_captured_requests(lines):
        captured = True
        request = _normalize(raw_request, timestamp_ms)
        if request is None or not _is_interesting(request):
            continue
        if len(kept) >= MAX_REQUESTS_PER_SESSION:
            truncated = True
            break
        kept.append(request)

    kept.sort(key=lambda request: request.timestamp_ms)
    return SessionNetworkPayload(requests=kept, captured=captured, truncated=truncated)


def _iter_captured_requests(lines: Iterable[str]) -> Iterator[tuple[dict[str, Any], int]]:
    """Yield `(raw request, event timestamp)` for every network plugin event across the snapshot lines."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        events = parsed.get("data")
        if not isinstance(events, list):
            continue
        for event in events:
            yield from _iter_event_requests(event)


def _iter_event_requests(event: Any) -> Iterator[tuple[dict[str, Any], int]]:
    """Yield the raw requests carried by one rrweb event, if it is a network plugin event."""
    if not isinstance(event, dict) or event.get("type") != _PLUGIN_EVENT_TYPE:
        return
    data = event.get("data")
    if not isinstance(data, dict):
        return
    plugin = data.get("plugin")
    payload = data.get("payload")
    timestamp = event.get("timestamp")
    if not isinstance(timestamp, int | float):
        return
    timestamp_ms = int(timestamp)

    if plugin == POSTHOG_NETWORK_PLUGIN:
        if isinstance(payload, dict):
            yield payload, timestamp_ms
    elif plugin == RRWEB_NETWORK_PLUGIN:
        if not isinstance(payload, dict):
            return
        requests = payload.get("requests")
        if not isinstance(requests, list):
            return
        for request in requests:
            if isinstance(request, dict):
                yield request, timestamp_ms


def _normalize(raw: dict[str, Any], timestamp_ms: int) -> NetworkRequest | None:
    """Map either plugin encoding onto `NetworkRequest`, or `None` when there is no usable URL.

    Headers and bodies are dropped here and never leave this function. They routinely carry auth tokens,
    session cookies and personal data, and the scanner's output is stored and shown to people, so the
    safe default is that they never reach the model at all.
    """
    fields: dict[str, Any] = {}
    for key, value in raw.items():
        field = _INDEXED_FIELDS.get(key) or _NAMED_FIELDS.get(key)
        if field is not None:
            fields[field] = value

    url = fields.get("name")
    if not isinstance(url, str) or not url.strip():
        return None

    return NetworkRequest(
        timestamp_ms=timestamp_ms,
        url=_clean_url(url),
        method=_as_str(fields.get("method")),
        status=_as_int(fields.get("response_status")),
        duration_ms=_as_int(fields.get("duration")),
        initiator=_as_str(fields.get("initiator_type")),
    )


def _clean_url(url: str) -> str:
    """Drop the query string and fragment, then bound the length.

    A query string carries the values the user typed or filtered by, which belong to other people: search
    terms, email addresses, record IDs, and sometimes a token. A failing endpoint is identified well
    enough by its method and path, so the parts that leak are not worth keeping.
    """
    url = url.strip()
    try:
        split = urlsplit(url)
    except ValueError:
        return url[:_MAX_URL_LENGTH]
    cleaned = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    if len(cleaned) > _MAX_URL_LENGTH:
        return cleaned[:_MAX_URL_LENGTH] + "…"
    return cleaned


def _is_interesting(request: NetworkRequest) -> bool:
    """Keep failures and slow requests; drop the successful traffic that explains nothing.

    Status 0 counts as a failure: wrapped fetch/xhr reports it when the request never completed, which is
    a blocked, aborted or offline request, and that is exactly what a stuck spinner looks like.
    """
    if request.status is not None and (request.status >= 400 or request.status == 0):
        return True
    return request.duration_ms is not None and request.duration_ms >= SLOW_REQUEST_MS


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return int(float(value))
    except (ValueError, OverflowError):
        return None


def _as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
