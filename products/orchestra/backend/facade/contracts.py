from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from .enums import ExecutionStatus


@dataclass(frozen=True)
class EventRecord:
    event_id: int
    event_type: str
    timestamp: datetime
    attributes: dict[str, Any]


@dataclass(frozen=True)
class ExecutionSummary:
    execution_id: str
    run_id: UUID
    execution_type: str
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class ExecutionDetail:
    execution_id: str
    run_id: UUID
    execution_type: str
    status: ExecutionStatus
    input: Any
    result: Any
    error: Any
    started_at: datetime
    finished_at: datetime | None
    events: list[EventRecord]


@dataclass(frozen=True)
class DeploymentSummary:
    id: int
    code_version: str
    image_name: str
    container_id: str
    task_queue: str
    status: str
    registered_executions: list[str]
    started_at: datetime
    finished_at: datetime | None
