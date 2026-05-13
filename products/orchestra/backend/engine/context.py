from __future__ import annotations

from typing import Any
from uuid import UUID

from .registry import StepFn, step_name
from .replay import ReplayState
from .types import Command, ScheduleStep, ScheduleTimer, StepFailed, _Suspend


class ExecutionContext:
    """Passed into execution functions; mediates durable step / timer calls."""

    def __init__(self, *, execution_id: str, run_id: UUID, state: ReplayState) -> None:
        self.execution_id = execution_id
        self.run_id = run_id
        self._state = state
        self._next_step_id = 0
        self._next_timer_id = 0
        self.commands: list[Command] = []

    async def step(self, fn: StepFn | str, input: Any = None) -> Any:
        sid = self._next_step_id
        self._next_step_id += 1
        name = step_name(fn)

        if sid in self._state.step_results:
            return self._state.step_results[sid]
        if sid in self._state.step_errors:
            raise StepFailed(name, self._state.step_errors[sid])

        self.commands.append(ScheduleStep(step_id=sid, step_type=name, input=input))
        raise _Suspend()

    async def sleep(self, seconds: float) -> None:
        tid = self._next_timer_id
        self._next_timer_id += 1

        if tid in self._state.timer_fired:
            return

        self.commands.append(ScheduleTimer(timer_id=tid, seconds=float(seconds)))
        raise _Suspend()
