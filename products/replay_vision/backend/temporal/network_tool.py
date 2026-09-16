"""The `get_network_around` tool: failed and slow network requests near a recording timestamp, on demand.

The video shows a spinner; it cannot show whether the request behind it returned a 500, was blocked, or
merely took four seconds. This tool lets the model settle that at the one moment it matters, without the
requests being dumped into the prompt.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from typing import Any

from google.genai import types

from products.replay_vision.backend.temporal.network_capture import NetworkRequest, SessionNetworkPayload

GET_NETWORK_TOOL_NAME = "get_network_around"

_DEFAULT_WINDOW_S = 10
_MAX_WINDOW_S = 60
_MAX_REQUESTS_RETURNED = 20


@dataclass(frozen=True)
class NetworkIndex:
    """Captured requests resolved once to recording-second offsets, so each lookup is a bisect.

    `offsets` is ascending and parallel to `requests`. An index with no requests means the tool is not
    offered for this scan at all, so the lookup paths below never have to describe that case.
    """

    offsets: list[int]
    requests: list[dict[str, Any]]
    truncated: bool = False

    def has_requests(self) -> bool:
        """Whether this recording has anything a lookup could return, which decides if the tool is offered."""
        return bool(self.offsets)


def build_network_index(payload: SessionNetworkPayload | None, session_start: dt.datetime | None) -> NetworkIndex:
    """Resolve each captured request to `rec_t` (seconds since the recording started).

    The anchor is the recording start the video footer and the events tool already use, so a `REC_T` the
    model reads off the footer addresses events and requests alike.
    """
    if payload is None or session_start is None:
        return NetworkIndex(offsets=[], requests=[])

    start_ms = int(session_start.timestamp() * 1000)
    entries: list[tuple[int, dict[str, Any]]] = []
    for request in payload.requests:
        offset_s = max(0, (request.timestamp_ms - start_ms) // 1000)
        entries.append((offset_s, _as_tool_dict(request, offset_s)))

    entries.sort(key=lambda entry: entry[0])
    return NetworkIndex(
        offsets=[offset for offset, _ in entries],
        requests=[request for _, request in entries],
        truncated=payload.truncated,
    )


def _as_tool_dict(request: NetworkRequest, offset_s: int) -> dict[str, Any]:
    """Render one request for the model, leaving out fields it has no value for."""
    entry: dict[str, Any] = {"rec_t": offset_s, "url": request.url}
    if request.method is not None:
        entry["method"] = request.method
    if request.status is not None:
        entry["status"] = request.status
    if request.duration_ms is not None:
        entry["duration_ms"] = request.duration_ms
    if request.initiator is not None:
        entry["initiator"] = request.initiator
    return entry


def get_network_around(index: NetworkIndex, rec_t: int, window_s: int = _DEFAULT_WINDOW_S) -> dict[str, Any]:
    """Return the captured requests within ±`window_s` seconds of `rec_t`, chronological and capped."""
    rec_t = max(0, rec_t)
    window_s = max(1, min(window_s, _MAX_WINDOW_S))

    lo = bisect.bisect_left(index.offsets, rec_t - window_s)
    hi = bisect.bisect_right(index.offsets, rec_t + window_s)
    window = index.requests[lo:hi]  # offsets are sorted, so this slice is already chronological
    if len(window) > _MAX_REQUESTS_RETURNED:
        # Keep the requests nearest `rec_t`, then restore chronological order.
        window = sorted(window, key=lambda request: abs(request["rec_t"] - rec_t))[:_MAX_REQUESTS_RETURNED]
        window.sort(key=lambda request: request["rec_t"])

    result: dict[str, Any] = {"requests": window}
    if not window:
        result["note"] = "No failed or slow requests in this window. Requests that succeeded quickly are not recorded."
    return result


def network_tool() -> types.Tool:
    """The Gemini function declaration for on-demand network lookups."""
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=GET_NETWORK_TOOL_NAME,
                description=(
                    "Look up the failed and slow network requests around a moment in the recording. Pass "
                    "`rec_t` — the footer's REC_T (whole seconds since the recording started). Only requests "
                    "that failed or took a long time are recorded, so use it to tell a broken request from a "
                    "slow one when the screen shows an error, a spinner, or a page that never loads."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "rec_t": types.Schema(
                            type=types.Type.INTEGER, description="Recording seconds — the footer's REC_T value."
                        ),
                        "window_s": types.Schema(
                            type=types.Type.INTEGER,
                            description=f"Half-window in seconds (default {_DEFAULT_WINDOW_S}).",
                        ),
                    },
                    required=["rec_t"],
                ),
            )
        ]
    )


def dispatch_network_tool(function_call: Any, index: NetworkIndex) -> dict[str, Any]:
    """Execute a model `get_network_around` call against the prebuilt index."""
    args = dict(getattr(function_call, "args", None) or {})
    rec_t = _parse_seconds(args.get("rec_t", 0))
    if rec_t is None:
        return {"error": "rec_t must be a number of recording seconds (the footer's REC_T value)"}
    window_s = _parse_seconds(args.get("window_s", _DEFAULT_WINDOW_S))
    if window_s is None:
        window_s = _DEFAULT_WINDOW_S
    return get_network_around(index, rec_t, window_s)


def _parse_seconds(value: Any) -> int | None:
    """Coerce a model-sent tool argument to whole seconds; `None` when it isn't numeric."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str):
            return int(float(value.strip()))
    except (ValueError, OverflowError):
        return None
    return None
