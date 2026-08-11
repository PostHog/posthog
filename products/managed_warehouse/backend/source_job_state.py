from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Max

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobRecord,
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobUpdate,
    ManagedWarehouseSourceJobWorkflow,
)
from products.managed_warehouse.backend.models import ManagedWarehouseSourceJob


def _to_record(
    job: ManagedWarehouseSourceJob, *, last_completed_at: datetime | None = None
) -> ManagedWarehouseSourceJobRecord:
    return ManagedWarehouseSourceJobRecord(
        id=job.id,
        team_id=job.team_id,
        environment_id=job.environment_id,
        schema_id=job.schema_id,
        source_job_id=job.source_job_id,
        attempt_id=job.attempt_id,
        workflow_type=ManagedWarehouseSourceJobWorkflow(job.workflow_type),
        status=ManagedWarehouseSourceJobStatus(job.status),
        started_at=job.started_at,
        finished_at=job.finished_at,
        latest_error=job.latest_error,
        workflow_id=job.workflow_id,
        workflow_run_id=job.workflow_run_id,
        last_completed_at=last_completed_at,
    )


@transaction.atomic
def record_source_job_state(update: ManagedWarehouseSourceJobUpdate) -> None:
    for schema_id in update.schema_ids:
        ManagedWarehouseSourceJob.objects.for_team(update.team_id).update_or_create(
            environment_id=update.team_id,
            schema_id=schema_id,
            workflow_type=update.workflow_type.value,
            attempt_id=update.attempt_id,
            defaults={
                "team_id": update.team_id,
                "source_job_id": update.source_job_id,
                "status": update.status.value,
                "workflow_id": update.workflow_id,
                "workflow_run_id": update.workflow_run_id,
                "started_at": update.started_at,
                "finished_at": update.finished_at,
                "latest_error": update.latest_error[:2000] if update.latest_error else None,
            },
        )


def list_latest_source_jobs(*, team_id: int, schema_ids: list[UUID]) -> list[ManagedWarehouseSourceJobRecord]:
    if not schema_ids:
        return []

    jobs = ManagedWarehouseSourceJob.objects.for_team(team_id).filter(
        environment_id=team_id,
        schema_id__in=schema_ids,
    )
    latest_jobs = jobs.order_by("schema_id", "-started_at", "-created_at").distinct("schema_id")
    last_completed_by_schema = dict(
        jobs.filter(status=ManagedWarehouseSourceJob.Status.COMPLETED)
        .values("schema_id")
        .annotate(last_completed_at=Max("finished_at"))
        .values_list("schema_id", "last_completed_at")
    )
    return [_to_record(job, last_completed_at=last_completed_by_schema.get(job.schema_id)) for job in latest_jobs]
