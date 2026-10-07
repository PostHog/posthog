"""Analytics events near a moment in the recording, keyed on video seconds.

The scan's lookup round reads these on the model's request, so events don't have to be dumped inline.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Type-only: importing `types` at runtime would trip the pre-existing types <-> scanners import cycle.
    from products.replay_vision.backend.temporal.types import ScannerLlmInputs
from products.replay_vision.backend.temporal.video_clock import VideoClock

_DEFAULT_WINDOW_S = 10
_MAX_WINDOW_S = 60
# A busy window can hold a lot of events; bound the response and keep the ones nearest `vid_t`.
_MAX_EVENTS_RETURNED = 50
# Internal columns the model doesn't need: the uuid is no longer cited, and the absolute timestamp
# is replaced by each event's video-relative `vid_t`.
_DROPPED_COLUMNS = frozenset({"event_uuid", "timestamp"})


@dataclass(frozen=True)
class EventsIndex:
    """Session events resolved once and sorted by recording-second offset, so each lookup is a bisect.

    `offsets` is ascending and parallel to `events`; build it once per scan with `build_events_index` and a
    `get_events_around` call becomes O(log n + k) instead of re-walking and re-resolving every event per call.
    """

    offsets: list[int]
    events: list[dict[str, Any]]


def build_events_index(llm_inputs: ScannerLlmInputs, clock: VideoClock) -> EventsIndex:
    """Resolve every event once and sort it by `vid_t` (seconds from the start of the video).

    For each event we drop the internal columns, map the `url`/`window` tokens back to real values, and tag it
    with `vid_t` converted from `event_timestamps` (ms since recording start) through `clock`, so events land on
    the same scale the model cites moments in. An event inside a stretch the rasterizer cut collapses onto that
    cut's position in the video, which is the only place it could be shown.
    """
    offsets = llm_inputs.event_timestamps
    url_mapping = llm_inputs.url_mapping
    window_mapping = llm_inputs.window_mapping

    entries: list[tuple[int, dict[str, Any]]] = []
    for raw in llm_inputs.events.as_dicts():  # `as_dicts` already drops null/empty fields
        offset_ms = offsets.get(str(raw.get("event_uuid", "")))
        if offset_ms is None:
            # No resolvable offset — skip rather than pin to second 0, which would pollute every vid_t≈0 window.
            continue
        offset_s = int(clock.session_ms_to_video_s(offset_ms))
        event: dict[str, Any] = {"vid_t": offset_s}
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


def get_events_around(index: EventsIndex, vid_t: int, window_s: int = _DEFAULT_WINDOW_S) -> list[dict[str, Any]]:
    """Return the events within ±`window_s` seconds of `vid_t`, chronological, capped to the nearest `_MAX_EVENTS_RETURNED`."""
    vid_t = max(0, vid_t)
    window_s = max(1, min(window_s, _MAX_WINDOW_S))

    lo = bisect.bisect_left(index.offsets, vid_t - window_s)
    hi = bisect.bisect_right(index.offsets, vid_t + window_s)
    window = index.events[lo:hi]  # offsets are sorted, so this slice is already chronological
    if len(window) > _MAX_EVENTS_RETURNED:
        # Keep the events nearest `vid_t`, then restore chronological order.
        window = sorted(window, key=lambda event: abs(event["vid_t"] - vid_t))[:_MAX_EVENTS_RETURNED]
        window.sort(key=lambda event: event["vid_t"])
    return window
