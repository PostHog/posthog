from __future__ import annotations

import uuid
import asyncio
from typing import Any

from django.conf import settings
from django.utils import timezone

from ..db import READER_DB
from ..engine.client import Client
from ..engine.db import Database
from ..models import Deployment, Event, Execution, Task
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
    team_id: int,
    status: str | None = None,
    execution_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[contracts.ExecutionSummary]:
    qs = Execution.all_teams.filter(team_id=team_id).order_by("-started_at")
    if status:
        qs = qs.filter(status=status)
    if execution_type:
        qs = qs.filter(execution_type=execution_type)
    return [_to_summary(obj) for obj in qs[offset : offset + limit]]


def get_execution(execution_id: str, *, team_id: int) -> contracts.ExecutionDetail:
    obj = Execution.all_teams.get(execution_id=execution_id, team_id=team_id)
    events = (
        Event.objects.using(READER_DB)
        .filter(execution_id=obj.execution_id, run_id=obj.run_id, team_id=team_id)
        .order_by("event_id")
    )
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


def _to_deployment_summary(obj: Deployment) -> contracts.DeploymentSummary:
    return contracts.DeploymentSummary(
        id=obj.id,
        code_version=obj.code_version,
        image_name=obj.image_name,
        container_id=obj.container_id,
        task_queue=obj.task_queue,
        status=obj.status,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
    )


def list_deployments(*, team_id: int, limit: int = 20) -> list[contracts.DeploymentSummary]:
    qs = Deployment.all_teams.filter(team_id=team_id).order_by("-started_at")[:limit]
    return [_to_deployment_summary(obj) for obj in qs]


def get_active_deployment(*, team_id: int) -> contracts.DeploymentSummary | None:
    obj = Deployment.all_teams.filter(team_id=team_id, status=Deployment.STATUS_ACTIVE).first()
    return _to_deployment_summary(obj) if obj else None


def register_deployment(
    *,
    team_id: int,
    code_version: str,
    image_name: str,
    container_id: str = "",
) -> contracts.DeploymentSummary:
    task_queue = f"team-{team_id}-{code_version[:12]}"
    Deployment.all_teams.filter(team_id=team_id, status=Deployment.STATUS_ACTIVE).update(
        status=Deployment.STATUS_DRAINING
    )
    obj = Deployment.all_teams.create(
        team_id=team_id,
        code_version=code_version,
        image_name=image_name,
        container_id=container_id,
        task_queue=task_queue,
        status=Deployment.STATUS_ACTIVE,
    )
    return _to_deployment_summary(obj)


def mark_deployment_stopped(*, deployment_id: int, team_id: int) -> contracts.DeploymentSummary | None:
    obj = Deployment.all_teams.filter(id=deployment_id, team_id=team_id).first()
    if obj is None:
        return None
    obj.status = Deployment.STATUS_STOPPED
    obj.finished_at = timezone.now()
    obj.save(update_fields=["status", "finished_at"])
    return _to_deployment_summary(obj)


def pending_task_count(*, team_id: int, task_queue: str) -> int:
    return Task.all_teams.filter(team_id=team_id, task_queue=task_queue).count()


def trigger_execution(
    *,
    team_id: int,
    execution_type: str,
    input: Any = None,
) -> str:
    active = Deployment.all_teams.filter(team_id=team_id, status=Deployment.STATUS_ACTIVE).first()
    if active is None:
        raise LookupError(f"no active deployment for team {team_id}")
    execution_id = f"{execution_type}-{uuid.uuid4().hex[:8]}"

    async def _run() -> None:
        db = await Database.connect(settings.ORCHESTRA_DSN)
        try:
            await Client(db).start_execution(
                execution_type,
                input,
                execution_id=execution_id,
                team_id=team_id,
                step_queue=active.task_queue,
            )
        finally:
            await db.close()

    asyncio.run(_run())
    return execution_id
