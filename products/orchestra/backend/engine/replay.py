from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import Event, EventType


@dataclass
class ReplayState:
    step_results: dict[int, Any] = field(default_factory=dict)
    step_errors: dict[int, Any] = field(default_factory=dict)
    step_step_types: dict[int, str] = field(default_factory=dict)
    timer_fired: set[int] = field(default_factory=set)
    is_done: bool = False
    final_result: Any = None
    final_error: Any = None


def build_replay_state(history: list[Event]) -> ReplayState:
    state = ReplayState()
    for ev in history:
        attrs = ev.attributes
        match ev.event_type:
            case EventType.STEP_SCHEDULED:
                state.step_step_types[int(attrs["step_id"])] = attrs["step_type"]
            case EventType.STEP_COMPLETED:
                state.step_results[int(attrs["step_id"])] = attrs.get("result")
            case EventType.STEP_FAILED:
                state.step_errors[int(attrs["step_id"])] = attrs.get("error")
            case EventType.TIMER_FIRED:
                state.timer_fired.add(int(attrs["timer_id"]))
            case EventType.EXECUTION_COMPLETED:
                state.is_done = True
                state.final_result = attrs.get("result")
            case EventType.EXECUTION_FAILED:
                state.is_done = True
                state.final_error = attrs.get("error")
    return state
