from __future__ import annotations

from ..models import Event, Execution
from . import contracts
from .enums import ExecutionStatus


def _to_summary(obj: Execution) -> contracts.ExecutionSummary:
    return contracts.ExecutionSummary(
        execution_id=obj.execution_id,
        run_id=obj.run_id,
        execution_type=obj.execution_type,
        status=ExecutionStatus(obj.status),
        started_at=obj.started_at,
        finished_at=obj.finished_at,
    )


def _to_event_record(obj: Event) -> contracts.EventRecord:
    return contracts.EventRecord(
        event_id=obj.event_id,
        event_type=obj.event_type,
        timestamp=obj.timestamp,
        attributes=obj.attributes,
    )


def list_executions(
    *,
    status: str | None = None,
    execution_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[contracts.ExecutionSummary]:
    qs = Execution.objects.all().order_by("-started_at")
    if status:
        qs = qs.filter(status=status)
    if execution_type:
        qs = qs.filter(execution_type=execution_type)
    return [_to_summary(obj) for obj in qs[offset : offset + limit]]


def get_execution(execution_id: str) -> contracts.ExecutionDetail:
    obj = Execution.objects.get(execution_id=execution_id)
    events = Event.objects.using("orchestra").filter(
        execution_id=obj.execution_id, run_id=obj.run_id
    ).order_by("event_id")
    return contracts.ExecutionDetail(
        execution_id=obj.execution_id,
        run_id=obj.run_id,
        execution_type=obj.execution_type,
        status=ExecutionStatus(obj.status),
        input=obj.input,
        result=obj.result,
        error=obj.error,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
        events=[_to_event_record(e) for e in events],
    )
