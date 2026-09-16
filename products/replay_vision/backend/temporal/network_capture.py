"""Decode rrweb network-plugin events out of a recording's snapshot blocks.

Network requests never reach ClickHouse. posthog-js captures them as rrweb plugin events that travel
inside the snapshot blobs, so the only way to read them server-side is to decode the blocks. The scanner
needs them because a failed request and a slow one look the same on video: both show a spinner.

A leaf module, so the activity and the tool can both import it without touching `types.py`, which
participates in an import cycle with the `scanners` package.
"""

from __future__ import annotations

import re
import json
from collections.abc import Iterable, Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field

# posthog-js emits `posthog/network@1` with the fields index-encoded as numeric string keys; rrweb's own
# recorder emits `rrweb/network@1` with named keys and several requests per event.
POSTHOG_NETWORK_PLUGIN = "posthog/network@1"
RRWEB_NETWORK_PLUGIN = "rrweb/network@1"

_PLUGIN_EVENT_TYPE = 6

# Mirrors `PerformanceEventReverseMapping` in
# frontend/src/scenes/session-recordings/apm/performance-event-utils.ts, reduced to the fields read here.
_INDEXED_FIELDS: dict[str, str] = {
    "0": "entry_type",
    "2": "name",
    "18": "initiator_type",
    "21": "response_status",
    "39": "duration",
}

_NAMED_FIELDS: dict[str, str] = {
    "entryType": "entry_type",
    "name": "name",
    # Wrapped fetch and xhr report the URL as `url`, not `name`. The frontend carries the same fallback
    # (`mapRRWebNetworkRequest`), so recordings in the wild use it and a request without it is dropped.
    "url": "name",
    "initiatorType": "initiator_type",
    "method": "method",
    "duration": "duration",
    "responseStatus": "response_status",
}

# The performance observer reports `responseStatus` and wrapped fetch/xhr reports `status`. When a request
# carries both, `status` wins, matching what the frontend shows for the same request.
_PREFERRED_STATUS_FIELD = "status"

# Above this a successful request is still worth showing, because it is what a user reads as a hang.
SLOW_REQUEST_MS = 1000

# A busy page issues thousands of requests; the scanner reads a few windows of them and the payload rides
# through Redis.
MAX_REQUESTS_PER_SESSION = 500

_MAX_URL_LENGTH = 200

# `method` and `initiator` come from the page and ride on every kept request.
_MAX_FIELD_LENGTH = 40


class NetworkRequest(BaseModel, frozen=True):
    """One captured request the scanner may be shown.

    `timestamp_ms` stays absolute (epoch milliseconds) because this payload is built without session
    metadata or the render's cut map. It is made session-relative and then projected onto video seconds
    when the tool index is built.
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
    # False when the SDK captured no network data at all, which the caller must not let the model read as
    # "nothing failed": with capture off an empty result is no evidence either way.
    captured: bool = False
    truncated: bool = False
    # True when a block could not be read, which makes the absence of failures unprovable.
    partial: bool = False


class NetworkCollector:
    """Accumulates the requests worth keeping as blocks arrive.

    Incremental so the caller can drop each block's lines once fed, and can stop fetching once `full`.
    Holding every block's lines to parse them in one pass made peak memory track the whole decompressed
    session, which the block count alone does not bound.
    """

    def __init__(self) -> None:
        self._captured = False
        self._kept: list[NetworkRequest] = []
        self._truncated = False

    @property
    def full(self) -> bool:
        return self._truncated

    def feed(self, lines: Iterable[str]) -> None:
        """Decode one block's snapshot lines, keeping the requests a scanner can act on."""
        if self._truncated:
            return
        for raw_request, timestamp_ms in _iter_captured_requests(lines):
            self._captured = True
            request = _normalize(raw_request, timestamp_ms)
            if request is None or not _is_interesting(request):
                continue
            if len(self._kept) >= MAX_REQUESTS_PER_SESSION:
                self._truncated = True
                return
            self._kept.append(request)

    def finish(self, *, partial: bool = False) -> SessionNetworkPayload:
        self._kept.sort(key=lambda request: request.timestamp_ms)
        return SessionNetworkPayload(
            requests=self._kept, captured=self._captured, truncated=self._truncated, partial=partial
        )


def parse_network_payload(lines: Iterable[str]) -> SessionNetworkPayload:
    """Decode every snapshot line and keep the requests a scanner can act on.

    Each line is one JSON object, `{"window_id": ..., "data": [event, ...]}`. Lines that don't parse are
    skipped rather than raised on: a single corrupt block must not lose a scan the rest of the session.
    """
    collector = NetworkCollector()
    collector.feed(lines)
    return collector.finish()


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

    if not isinstance(payload, dict):
        return
    requests: list[Any]
    if plugin == POSTHOG_NETWORK_PLUGIN:
        requests = [payload]
    elif plugin == RRWEB_NETWORK_PLUGIN:
        raw_requests = payload.get("requests")
        requests = raw_requests if isinstance(raw_requests, list) else []
    else:
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
    if _PREFERRED_STATUS_FIELD in raw:
        fields["response_status"] = raw[_PREFERRED_STATUS_FIELD]
    if isinstance(raw.get("name"), str):
        fields["name"] = raw["name"]

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
        # Still cut at the first `?` or `#`: a URL too malformed to split is client-supplied text that
        # can carry a token just as readily as a well-formed one.
        return re.split(r"[?#]", url, maxsplit=1)[0][:_MAX_URL_LENGTH]
    # `netloc` carries any `user:password@` prefix, so rebuild the authority from the host and port.
    host = split.hostname or ""
    authority = f"{host}:{split.port}" if split.port else host
    cleaned = urlunsplit((split.scheme, authority, split.path, "", ""))
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
    """Coerce to a bounded string. These come from the page, so length is not ours to trust."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:_MAX_FIELD_LENGTH] if value else None
