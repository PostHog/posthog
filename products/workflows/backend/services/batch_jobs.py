from collections.abc import Collection
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.workflows.backend.facade.contracts import WorkflowBatchJob, WorkflowBatchJobNotFound
from products.workflows.backend.facade.enums import HogFlowBatchJobState, HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import (
    batch_job_audience_filters,
    dispatch_batch_job,
)
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.services.batch_audience_cohorts import (
    realtime_audience_cohort,
    realtime_cohort_is_ready,
)

if TYPE_CHECKING:
    from products.cohorts.backend.models.cohort import Cohort

logger = structlog.get_logger(__name__)

# A run waits this long for its realtime cohort to finish calculating, then fails.
REALTIME_COHORT_WAIT_LIMIT = timedelta(hours=24)


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


def cancel_waiting_batch_job(*, team_id: int, batch_job_id: UUID) -> bool:
    """Cancel a run that still waits for its realtime cohort. False when it already left that state."""
    return (
        HogFlowBatchJob.objects.filter(team_id=team_id, pk=batch_job_id, status=HogFlowBatchJobState.WAITING).update(
            status=HogFlowBatchJobState.CANCELLED
        )
        == 1
    )


def dispatch_batch_jobs_waiting_for_cohorts() -> None:
    """Start each run that waits for its realtime cohort, once that cohort's membership is calculated.

    Every waiting run is checked on each pass, so runs whose cohorts are still calculating don't
    hold back the rest. A run whose workflow stopped being active is cancelled, and a run that
    waits past REALTIME_COHORT_WAIT_LIMIT fails.
    """
    waiting = (
        HogFlowBatchJob.objects.filter(status=HogFlowBatchJobState.WAITING)
        .select_related("team", "hog_flow")
        .order_by("created_at")
    )
    for job in waiting.iterator(chunk_size=500):
        still_waiting = HogFlowBatchJob.objects.filter(pk=job.pk, status=HogFlowBatchJobState.WAITING)
        if job.hog_flow.status != HogFlow.State.ACTIVE:
            still_waiting.update(status=HogFlowBatchJobState.CANCELLED, updated_at=timezone.now())
            continue
        realtime_cohort = realtime_audience_cohort(job.team.project_id, batch_job_audience_filters(job))
        if realtime_cohort is not None and not realtime_cohort_is_ready(realtime_cohort):
            if job.created_at < timezone.now() - REALTIME_COHORT_WAIT_LIMIT:
                logger.warning("realtime_cohort_wait_expired", batch_job_id=str(job.id), cohort_id=realtime_cohort.pk)
                still_waiting.update(status=HogFlowBatchJobState.FAILED, updated_at=timezone.now())
            continue
        _dispatch_waiting_batch_job(job, realtime_cohort)


def _dispatch_waiting_batch_job(job: HogFlowBatchJob, realtime_cohort: "Cohort | None") -> None:
    # The row lock makes a stop that arrives during the dispatch wait for it. The stop then finds
    # the run queued and cancels its resolver, instead of marking a run cancelled that still sends.
    with transaction.atomic():
        claimed = (
            HogFlowBatchJob.objects.select_for_update(skip_locked=True)
            .filter(pk=job.pk, status=HogFlowBatchJobState.WAITING)
            .exists()
        )
        if not claimed:
            return
        try:
            dispatch_batch_job(job, realtime_cohort).raise_for_status()
            status = HogFlowBatchJobState.QUEUED
        except Exception as error:
            # The CDP API may have enqueued the resolver before the error, so a retry could send
            # twice. The run fails instead, and the sender can start it again.
            logger.exception("waiting_batch_job_dispatch_failed", batch_job_id=str(job.id))
            capture_exception(error)
            status = HogFlowBatchJobState.FAILED
        HogFlowBatchJob.objects.filter(pk=job.pk).update(status=status, updated_at=timezone.now())
