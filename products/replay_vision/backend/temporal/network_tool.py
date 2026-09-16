"""The `get_network_around` tool: failed and slow network requests near a moment in the video, on demand.

The video shows a spinner; it cannot show whether the request behind it returned a 500, was blocked, or
merely took four seconds. This tool lets the model settle that at the one moment it matters, without the
requests being dumped into the prompt.
"""

from __future__ import annotations

import bisect
import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal

from google.genai import types

from products.replay_vision.backend.temporal.network_capture import NetworkRequest, SessionNetworkPayload
from products.replay_vision.backend.temporal.tool_args import parse_seconds
from products.replay_vision.backend.temporal.video_clock import VideoClock

GET_NETWORK_TOOL_NAME = "get_network_around"

_DEFAULT_WINDOW_S = 10
_MAX_WINDOW_S = 60
_MAX_REQUESTS_RETURNED = 20


@dataclass(frozen=True)
class NetworkIndex:
    """Captured requests resolved once to video-second offsets, so each lookup is a bisect.

    `offsets` is ascending and parallel to `requests`. This object is the single source of truth for
    whether a scan offers the network tool: the same instance decides the tool list and the preamble
    wording, so the prompt can never promise a tool the conversation does not carry.
    """

    offsets: list[int]
    requests: list[dict[str, Any]]
    captured: bool = False
    truncated: bool = False
    partial: bool = False

    def has_requests(self) -> bool:
        """Whether this recording has anything a lookup could return, which decides if the tool is offered."""
        return bool(self.offsets)

    def state(self) -> Literal["available", "clean", "none"]:
        """How the preamble describes network data for this scan.

        `clean` and `none` both withhold the tool but are not the same evidence. `clean` says the SDK
        captured requests and none failed, which lets a scanner rule a network cause out. `none` says
        nothing was captured, so silence means nothing either way.
        """
        if self.has_requests():
            return "available"
        # A truncated or partial read cannot show that nothing failed: the requests it did not reach are
        # unknown, so the honest answer is no evidence rather than evidence of absence.
        if self.captured and not self.truncated and not self.partial:
            return "clean"
        return "none"


def build_network_index(
    payload: SessionNetworkPayload | None, session_start: dt.datetime | None, clock: VideoClock
) -> NetworkIndex:
    """Resolve each captured request to `vid_t` (seconds from the start of the video).

    A request carries an absolute timestamp, so it is first made session-relative and then projected
    through `clock`, which lands it on the same scale the events tool and the model's citations use. A
    request inside a stretch the rasterizer cut collapses onto that cut's position, the only place in the
    video it could be shown.
    """
    if payload is None or session_start is None:
        return NetworkIndex(offsets=[], requests=[])

    # ClickHouse hands back naive datetimes. Reading one as UTC here is correct only because Django
    # forces the process timezone to UTC at startup, so state the assumption locally instead.
    anchor = session_start if session_start.tzinfo is not None else session_start.replace(tzinfo=dt.UTC)
    start_ms = int(anchor.timestamp() * 1000)
    entries: list[tuple[int, dict[str, Any]]] = []
    for request in payload.requests:
        session_ms = max(0, request.timestamp_ms - start_ms)
        offset_s = max(0, int(clock.session_ms_to_video_s(session_ms)))
        entries.append((offset_s, _as_tool_dict(request, offset_s)))

    entries.sort(key=lambda entry: entry[0])
    return NetworkIndex(
        offsets=[offset for offset, _ in entries],
        requests=[request for _, request in entries],
        captured=payload.captured,
        truncated=payload.truncated,
        partial=payload.partial,
    )


def _as_tool_dict(request: NetworkRequest, offset_s: int) -> dict[str, Any]:
    """Render one request for the model, leaving out fields it has no value for."""
    entry: dict[str, Any] = {"vid_t": offset_s, "url": request.url}
    if request.method is not None:
        entry["method"] = request.method
    if request.status is not None:
        entry["status"] = request.status
    if request.duration_ms is not None:
        entry["duration_ms"] = request.duration_ms
    if request.initiator is not None:
        entry["initiator"] = request.initiator
    return entry


def get_network_around(index: NetworkIndex, vid_t: int, window_s: int = _DEFAULT_WINDOW_S) -> dict[str, Any]:
    """Return the captured requests within ±`window_s` seconds of `vid_t`, chronological and capped."""
    vid_t = max(0, vid_t)
    window_s = max(1, min(window_s, _MAX_WINDOW_S))

    lo = bisect.bisect_left(index.offsets, vid_t - window_s)
    hi = bisect.bisect_right(index.offsets, vid_t + window_s)
    window = index.requests[lo:hi]  # offsets are sorted, so this slice is already chronological
    if len(window) > _MAX_REQUESTS_RETURNED:
        # Keep the requests nearest `vid_t`, then restore chronological order.
        window = sorted(window, key=lambda request: abs(request["vid_t"] - vid_t))[:_MAX_REQUESTS_RETURNED]
        window.sort(key=lambda request: request["vid_t"])

    result: dict[str, Any] = {"requests": window}
    if index.truncated or index.partial:
        result["note"] = "Some of this session's requests could not be read, so this window may be incomplete."
    elif not window:
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
                    "`vid_t` — whole seconds from the start of the video, the same scale you cite moments in. "
                    "Only requests that failed or took a long time are recorded, so use it to tell a broken "
                    "request from a slow one when the screen shows an error, a spinner, or a page that never loads."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "vid_t": types.Schema(
                            type=types.Type.INTEGER, description="Video seconds from the start of the video."
                        ),
                        "window_s": types.Schema(
                            type=types.Type.INTEGER,
                            description=f"Half-window in seconds (default {_DEFAULT_WINDOW_S}).",
                        ),
                    },
                    required=["vid_t"],
                ),
            )
        ]
    )


def dispatch_network_tool(function_call: Any, index: NetworkIndex) -> dict[str, Any]:
    """Execute a model `get_network_around` call against the prebuilt index."""
    if getattr(function_call, "name", None) != GET_NETWORK_TOOL_NAME:
        return {"error": f"unknown tool: {getattr(function_call, 'name', None)}"}
    args = dict(getattr(function_call, "args", None) or {})
    vid_t = parse_seconds(args.get("vid_t"))
    if vid_t is None:
        return {"error": "vid_t must be a number of seconds from the start of the video"}
    window_s = parse_seconds(args.get("window_s", _DEFAULT_WINDOW_S))
    if window_s is None:
        window_s = _DEFAULT_WINDOW_S
    return get_network_around(index, vid_t, window_s)
