from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


class EventType:
    EXECUTION_STARTED = "EXECUTION_STARTED"
    STEP_SCHEDULED = "STEP_SCHEDULED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    TIMER_SCHEDULED = "TIMER_SCHEDULED"
    TIMER_FIRED = "TIMER_FIRED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class TaskType:
    EXECUTION_TASK = "EXECUTION_TASK"
    STEP_TASK = "STEP_TASK"
    TIMER_TASK = "TIMER_TASK"


class ExecutionStatus:
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Event:
    execution_id: str
    run_id: UUID
    event_id: int
    event_type: str
    timestamp: datetime
    attributes: dict[str, Any]


@dataclass(frozen=True)
class Task:
    task_id: UUID
    task_queue: str
    task_type: str
    execution_id: str
    run_id: UUID
    scheduled_event_id: int | None
    step_type: str | None
    input: Any
    visible_at: datetime
    locked_by: str | None
    locked_until: datetime | None
    attempt: int
    team_id: int


@dataclass(frozen=True)
class ScheduleStep:
    step_id: int
    step_type: str
    input: Any


@dataclass(frozen=True)
class ScheduleTimer:
    timer_id: int
    seconds: float


Command = ScheduleStep | ScheduleTimer


class StepFailed(Exception):
    def __init__(self, step_type: str, error: Any) -> None:
        super().__init__(f"step {step_type!r} failed: {error}")
        self.step_type = step_type
        self.error = error


class _Suspend(BaseException):
    """Raised inside an execution function to abort the current attempt.

    Inherits BaseException so user `except Exception` blocks don't swallow it.
    """
