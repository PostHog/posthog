from __future__ import annotations

import time
import uuid
import asyncio
import logging
import threading
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from posthog.utils import relative_date_parse

from ..build import run_user_container, stop_container
from ..db import READER_DB
from ..engine.client import Client
from ..engine.db import Database
from ..models import Deployment, Event, Execution, Task
from . import contracts
from .enums import ExecutionStatus

logger = logging.getLogger("orchestra.facade")


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
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[contracts.ExecutionSummary]:
    qs = Execution.all_teams.filter(team_id=team_id).order_by("-started_at")
    if status:
        qs = qs.filter(status=status)
    if execution_type:
        qs = qs.filter(execution_type=execution_type)
    tz = ZoneInfo("UTC")
    if date_from:
        qs = qs.filter(started_at__gte=relative_date_parse(date_from, tz))
    if date_to:
        qs = qs.filter(started_at__lte=relative_date_parse(date_to, tz, increase=True))
    seen: set[str] = set()
    deduped: list[contracts.ExecutionSummary] = []
    for obj in qs.iterator():
        if obj.execution_id in seen:
            continue
        seen.add(obj.execution_id)
        if len(deduped) >= offset + limit:
            break
        deduped.append(_to_summary(obj))
    return deduped[offset : offset + limit]


def get_execution(execution_id: str, *, team_id: int) -> contracts.ExecutionDetail:
    obj = (
        Execution.all_teams.filter(execution_id=execution_id, team_id=team_id)
        .order_by("-started_at")
        .first()
    )
    if obj is None:
        raise Execution.DoesNotExist(f"execution {execution_id} not found")
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
        registered_executions=list(obj.registered_executions or []),
        started_at=obj.started_at,
        finished_at=obj.finished_at,
    )


def list_deployments(
    *,
    team_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
) -> list[contracts.DeploymentSummary]:
    qs = Deployment.all_teams.filter(team_id=team_id).order_by("-started_at")
    tz = ZoneInfo("UTC")
    if date_from:
        qs = qs.filter(started_at__gte=relative_date_parse(date_from, tz))
    if date_to:
        qs = qs.filter(started_at__lte=relative_date_parse(date_to, tz, increase=True))
    return [_to_deployment_summary(obj) for obj in qs[:limit]]


def get_active_deployment(*, team_id: int) -> contracts.DeploymentSummary | None:
    obj = Deployment.all_teams.filter(team_id=team_id, status=Deployment.STATUS_ACTIVE).first()
    return _to_deployment_summary(obj) if obj else None


def _make_task_queue(team_id: int, code_version: str) -> str:
    return f"team-{team_id}-{code_version[:12]}"


def register_deployment(
    *,
    team_id: int,
    code_version: str,
    image_name: str,
    container_id: str = "",
    registered_executions: list[str] | None = None,
) -> contracts.DeploymentSummary:
    task_queue = _make_task_queue(team_id, code_version)
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
        registered_executions=list(registered_executions or []),
    )
    return _to_deployment_summary(obj)


def deploy_existing_image(
    *,
    team_id: int,
    code_version: str,
    image_name: str,
    registered_executions: list[str] | None = None,
) -> contracts.DeploymentSummary:
    """Skip the build, run an already-tagged image, then register + drain previous."""
    task_queue = _make_task_queue(team_id, code_version)
    container_id = run_user_container(
        team_id=team_id,
        code_version=code_version,
        image_name=image_name,
        modules=None,
        task_queue=task_queue,
    )

    previous_active = Deployment.all_teams.filter(team_id=team_id, status=Deployment.STATUS_ACTIVE).first()

    summary = register_deployment(
        team_id=team_id,
        code_version=code_version,
        image_name=image_name,
        container_id=container_id,
        registered_executions=registered_executions,
    )

    if previous_active is not None:
        previous_active.refresh_from_db()
        _spawn_drain_monitor(
            team_id=team_id,
            deployment_id=previous_active.id,
            container_id=previous_active.container_id,
            task_queue=previous_active.task_queue,
        )
    return summary


def _spawn_drain_monitor(
    *,
    team_id: int,
    deployment_id: int,
    container_id: str,
    task_queue: str,
) -> None:
    """Start a daemon thread that stops the draining container once its queue empties.

    Process-local: a PostHog restart leaves the old container running. Good enough
    for the POC; production would reconcile from the Deployment table on boot.
    """
    poll_interval = float(getattr(settings, "ORCHESTRA_DRAIN_POLL_INTERVAL", 5.0))

    def _monitor() -> None:
        logger.info(
            "drain monitor started team=%s deployment=%s queue=%s",
            team_id,
            deployment_id,
            task_queue,
        )
        while True:
            time.sleep(poll_interval)
            pending = pending_task_count(team_id=team_id, task_queue=task_queue)
            if pending == 0:
                logger.info("drain complete team=%s deployment=%s", team_id, deployment_id)
                stop_container(container_id)
                mark_deployment_stopped(deployment_id=deployment_id, team_id=team_id)
                return

    threading.Thread(
        target=_monitor,
        name=f"orchestra-drain-{deployment_id}",
        daemon=True,
    ).start()


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


def retry_execution(*, team_id: int, execution_id: str) -> str:
    """Fork a new run for a previously failed execution, reusing its completed step state.

    Returns the same `execution_id` (a retry shares the execution_id; only the
    `run_id` changes). Raises `LookupError` if no such execution exists for the
    team. Raises `ValueError` if the latest run is not in FAILED status.
    """
    if not Execution.all_teams.filter(execution_id=execution_id, team_id=team_id).exists():
        raise LookupError(f"execution {execution_id} not found")

    async def _run() -> None:
        db = await Database.connect(settings.ORCHESTRA_DSN)
        try:
            await Client(db).retry_execution(execution_id=execution_id, team_id=team_id)
        finally:
            await db.close()

    asyncio.run(_run())
    return execution_id
