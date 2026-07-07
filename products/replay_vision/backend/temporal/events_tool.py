"""The `get_events_around` tool: analytics events near a recording timestamp, on demand.

Exposed to the scanner LLM so events don't have to be dumped inline — the model watches the video
and pulls event context for a moment only when it needs it, keyed on the footer's `REC_T`.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from google.genai import types

if TYPE_CHECKING:
    # Type-only: importing `types` at runtime would trip the pre-existing types <-> scanners import cycle.
    from products.replay_vision.backend.temporal.types import ScannerLlmInputs

GET_EVENTS_TOOL_NAME = "get_events_around"

_DEFAULT_WINDOW_S = 10
_MAX_WINDOW_S = 60
# A busy window can hold a lot of events; bound the response and keep the ones nearest `rec_t`.
_MAX_EVENTS_RETURNED = 50
# Internal columns the model doesn't need: the uuid is no longer cited, and the absolute timestamp
# is replaced by each event's recording-relative `rec_t`.
_DROPPED_COLUMNS = frozenset({"event_uuid", "timestamp"})


@dataclass(frozen=True)
class EventsIndex:
    """Session events resolved once and sorted by recording-second offset, so each lookup is a bisect.

    `offsets` is ascending and parallel to `events`; build it once per scan with `build_events_index` and a
    `get_events_around` call becomes O(log n + k) instead of re-walking and re-resolving every event per call.
    """

    offsets: list[int]
    events: list[dict[str, Any]]


def build_events_index(llm_inputs: ScannerLlmInputs) -> EventsIndex:
    """Resolve every event once and sort it by `rec_t` (seconds since the recording started).

    For each event we drop the internal columns, map the `url`/`window` tokens back to real values, and tag it
    with `rec_t` from `event_timestamps` (ms since recording start) — the same recording-start anchor the footer
    and citation timestamps use, so there's no session-vs-recording skew.
    """
    offsets = llm_inputs.event_timestamps
    url_mapping = llm_inputs.url_mapping
    window_mapping = llm_inputs.window_mapping

    entries: list[tuple[int, dict[str, Any]]] = []
    for raw in llm_inputs.events.as_dicts():  # `as_dicts` already drops null/empty fields
        offset_ms = offsets.get(str(raw.get("event_uuid", "")))
        if offset_ms is None:
            # No resolvable offset — skip rather than pin to second 0, which would pollute every rec_t≈0 window.
            continue
        offset_s = offset_ms // 1000
        event: dict[str, Any] = {"rec_t": offset_s}
        for column, value in raw.items():
            if column in _DROPPED_COLUMNS:
                continue
            if column == "$current_url":
                value = url_mapping.get(value, value)
            elif column == "$window_id":
                value = window_mapping.get(value, value)
            event[column] = value
        entries.append((offset_s, event))

    entries.sort(key=lambda entry: entry[0])
    return EventsIndex(offsets=[offset for offset, _ in entries], events=[event for _, event in entries])


def get_events_around(index: EventsIndex, rec_t: int, window_s: int = _DEFAULT_WINDOW_S) -> list[dict[str, Any]]:
    """Return the events within ±`window_s` seconds of `rec_t`, chronological, capped to the nearest `_MAX_EVENTS_RETURNED`."""
    rec_t = max(0, rec_t)
    window_s = max(1, min(window_s, _MAX_WINDOW_S))

    lo = bisect.bisect_left(index.offsets, rec_t - window_s)
    hi = bisect.bisect_right(index.offsets, rec_t + window_s)
    window = index.events[lo:hi]  # offsets are sorted, so this slice is already chronological
    if len(window) > _MAX_EVENTS_RETURNED:
        # Keep the events nearest `rec_t`, then restore chronological order.
        window = sorted(window, key=lambda event: abs(event["rec_t"] - rec_t))[:_MAX_EVENTS_RETURNED]
        window.sort(key=lambda event: event["rec_t"])
    return window


def events_tool() -> types.Tool:
    """The Gemini function declaration the scanner offers, so the model can pull event context on demand."""
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=GET_EVENTS_TOOL_NAME,
                description=(
                    "Look up the analytics events around a moment in the recording. Pass `rec_t` — the footer's "
                    "REC_T (whole seconds since the recording started). Use it to check what the event log captured "
                    "at that moment, e.g. whether a $rageclick, $dead_click or $exception is recorded there."
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


def dispatch_events_tool(function_call: Any, index: EventsIndex) -> dict[str, Any]:
    """Execute a model `get_events_around` call against the prebuilt events index."""
    if getattr(function_call, "name", None) != GET_EVENTS_TOOL_NAME:
        return {"error": f"unknown tool: {getattr(function_call, 'name', None)}"}
    args = dict(getattr(function_call, "args", None) or {})
    # Errors go back to the model as tool output — a malformed call must not fail the billed conversation.
    rec_t = _parse_seconds(args.get("rec_t", 0))
    if rec_t is None:
        return {"error": "rec_t must be a number of recording seconds (the footer's REC_T value)"}
    window_s = _parse_seconds(args.get("window_s", _DEFAULT_WINDOW_S))
    if window_s is None:
        window_s = _DEFAULT_WINDOW_S
    return {"events": get_events_around(index, rec_t, window_s)}
