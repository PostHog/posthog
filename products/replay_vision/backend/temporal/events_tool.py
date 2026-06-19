"""The `get_events_around` tool: analytics events near a recording timestamp, on demand.

Exposed to the scanner LLM so events don't have to be dumped inline — the model watches the video
and pulls event context for a moment only when it needs it, keyed on the footer's `REC_T`.
"""

from __future__ import annotations

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


def get_events_around(
    llm_inputs: ScannerLlmInputs, rec_t: int, window_s: int = _DEFAULT_WINDOW_S
) -> list[dict[str, Any]]:
    """Return the analytics events within ±`window_s` seconds of `rec_t`, nearest first when capped.

    `rec_t` is the footer's `REC_T`: seconds since the **recording** started. Event positions come from
    `event_timestamps` (ms since recording start) — the same recording-start anchor the footer and the
    citation timestamps use. We compare `rec_t` directly against those, so there is no session-vs-recording
    skew (the recording can begin well after the session does, but both sides here are recording-relative).
    """
    rec_t = max(0, rec_t)
    window_s = max(1, min(window_s, _MAX_WINDOW_S))

    columns = llm_inputs.events.columns
    offsets = llm_inputs.event_timestamps
    url_mapping = llm_inputs.url_mapping
    window_mapping = llm_inputs.window_mapping
    uuid_index = columns.index("event_uuid") if "event_uuid" in columns else None

    matches: list[tuple[int, dict[str, Any]]] = []
    for row in llm_inputs.events.rows:
        uuid = str(row[uuid_index]) if uuid_index is not None else ""
        offset_s = offsets.get(uuid, 0) // 1000
        distance = abs(offset_s - rec_t)
        if distance > window_s:
            continue
        event: dict[str, Any] = {"rec_t": offset_s}
        for column, value in zip(columns, row):
            # Mirror `EventTable.as_dicts`: drop internal columns and null/empty values so sparse events stay compact.
            if column in _DROPPED_COLUMNS or value is None or value == "" or value == [] or value == {}:
                continue
            if column == "$current_url":
                value = url_mapping.get(value, value)
            elif column == "$window_id":
                value = window_mapping.get(value, value)
            event[column] = value
        matches.append((distance, event))

    matches.sort(key=lambda m: m[0])  # nearest to `rec_t` survive the cap
    nearest = [event for _, event in matches[:_MAX_EVENTS_RETURNED]]
    nearest.sort(key=lambda event: event["rec_t"])  # then present chronologically
    return nearest


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


def dispatch_events_tool(function_call: Any, llm_inputs: ScannerLlmInputs) -> dict[str, Any]:
    """Execute a model `get_events_around` call against the session's already-fetched events."""
    if getattr(function_call, "name", None) != GET_EVENTS_TOOL_NAME:
        return {"error": f"unknown tool: {getattr(function_call, 'name', None)}"}
    args = dict(getattr(function_call, "args", None) or {})
    rec_t = int(args.get("rec_t", 0))
    window_s = int(args.get("window_s", _DEFAULT_WINDOW_S))
    return {"events": get_events_around(llm_inputs, rec_t, window_s)}
