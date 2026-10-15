from collections.abc import Collection
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

from products.workflows.backend.facade.contracts import WorkflowBatchJob, WorkflowBatchJobNotFound
from products.workflows.backend.facade.enums import HogFlowBatchJobState, HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule


def to_batch_job(job: HogFlowBatchJob) -> WorkflowBatchJob:
    return WorkflowBatchJob(
        id=job.id,
        hog_flow_id=job.hog_flow_id,
        status=HogFlowBatchJobState(job.status),
        filters=job.filters,
        variables=job.variables,
        created_at=job.created_at,
        updated_at=job.updated_at,
        created_by=job.created_by,
    )


def create_batch_job(
    *,
    team_id: int,
    hog_flow_id: UUID,
    created_by_id: int,
    variables: dict[str, Any],
    filters: dict[str, Any],
    status: HogFlowBatchJobState | None = None,
) -> WorkflowBatchJob:
    """Save the job row. Its post_save receiver dispatches the run to the plugin server."""
    job = HogFlowBatchJob.objects.create(
        team_id=team_id,
        hog_flow_id=hog_flow_id,
        created_by_id=created_by_id,
        variables=variables,
        filters=filters,
        **({} if status is None else {"status": status}),
    )
    return to_batch_job(job)


def list_batch_jobs(*, team_id: int, hog_flow_id: UUID) -> list[WorkflowBatchJob]:
    jobs = HogFlowBatchJob.objects.filter(hog_flow_id=hog_flow_id, team_id=team_id).order_by("-created_at")
    return [to_batch_job(job) for job in jobs]


def get_batch_job(*, team_id: int, batch_job_id: str, hog_flow_id: UUID | None = None) -> WorkflowBatchJob:
    lookup: dict[str, Any] = {"id": batch_job_id, "team_id": team_id}
    if hog_flow_id is not None:
        lookup["hog_flow_id"] = hog_flow_id
    try:
        return to_batch_job(HogFlowBatchJob.objects.get(**lookup))
    except (HogFlowBatchJob.DoesNotExist, DjangoValidationError, ValueError):
        # DjangoValidationError fires when the id is not a parseable UUID.
        raise WorkflowBatchJobNotFound()


def set_batch_job_status(
    *,
    team_id: int,
    batch_job_id: UUID,
    status: HogFlowBatchJobState,
    from_statuses: Collection[HogFlowBatchJobState] | None = None,
) -> None:
    """Write the status. With from_statuses, only a job still in one of them changes."""
    jobs = HogFlowBatchJob.objects.filter(id=batch_job_id, team_id=team_id)
    if from_statuses is not None:
        jobs = jobs.filter(status__in=from_statuses)
    # `.update()` bypasses auto_now, so stamp updated_at explicitly.
    jobs.update(status=status, updated_at=timezone.now())


def hog_flow_ids_with_broadcast_status(*, team_id: int, statuses: Collection[str]) -> list[UUID]:
    # The status a sender sees on a broadcast, derived the way the broadcasts UI derives it: from the
    # latest run and whether a schedule still has sends to come.
    latest_run_status = (
        HogFlowBatchJob.objects.filter(team_id=OuterRef("team_id"), hog_flow_id=OuterRef("pk"))
        .order_by("-created_at")
        .values("status")[:1]
    )
    queryset = HogFlow.objects.filter(team_id=team_id).annotate(
        _latest_run_status=Subquery(latest_run_status),
        _has_pending_schedule=Exists(
            HogFlowSchedule.objects.filter(
                team_id=OuterRef("team_id"), hog_flow_id=OuterRef("pk"), status=HogFlowScheduleStatus.ACTIVE
            )
        ),
    )
    live = Q(status=HogFlow.State.ACTIVE)
    # Only a wizard launch always leaves a schedule or a run. An opened workflow can wait for an API send.
    nothing_to_come = Q(_latest_run_status__isnull=True, _has_pending_schedule=False)
    unfinished_launch = nothing_to_come & Q(origin_product="broadcasts")
    running = [HogFlowBatchJobState.WAITING, HogFlowBatchJobState.QUEUED, HogFlowBatchJobState.ACTIVE]
    conditions = {
        "draft": Q(status=HogFlow.State.DRAFT),
        "archived": Q(status=HogFlow.State.ARCHIVED),
        "sending": live & Q(_latest_run_status__in=running),
        "sent": live & Q(_latest_run_status=HogFlowBatchJobState.COMPLETED, _has_pending_schedule=False),
        "scheduled": live
        & (
            (
                Q(_has_pending_schedule=True)
                & (Q(_latest_run_status__isnull=True) | Q(_latest_run_status=HogFlowBatchJobState.COMPLETED))
            )
            | (nothing_to_come & ~Q(origin_product="broadcasts"))
        ),
        "failed": live
        & (Q(_latest_run_status__in=[HogFlowBatchJobState.FAILED, HogFlowBatchJobState.CANCELLED]) | unfinished_launch),
    }
    combined = Q()
    for broadcast_status in statuses:
        combined |= conditions[broadcast_status]
    return list(queryset.filter(combined).values_list("id", flat=True))
