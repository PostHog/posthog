from collections.abc import Collection
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q, Subquery
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.plugins.plugin_server_api import resume_hog_flow_batch_job

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.facade.contracts import WorkflowBatchJob, WorkflowBatchJobNotFound
from products.workflows.backend.facade.enums import HogFlowBatchJobState, HogFlowScheduleStatus
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import batch_job_audience_filters
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.services.batch_audience_cohorts import realtime_cohort_is_ready, sole_audience_cohort_id

logger = structlog.get_logger(__name__)


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


def delete_batch_jobs_for_teams(team_ids: Collection[int], batch_size: int = 1000) -> None:
    jobs = HogFlowBatchJob.objects.filter(team_id__in=team_ids)
    while batch_ids := list(jobs.values_list("id", flat=True)[:batch_size]):
        jobs.filter(id__in=batch_ids).delete()


REALTIME_COHORT_RESUMES = Counter(
    "workflows_realtime_cohort_resume_total",
    "Batch runs woken after their realtime cohort finished calculating, by the CDP API's outcome.",
    labelnames=["outcome"],
)


def resume_batch_jobs_waiting_for_cohort(*, team_id: int, cohort_id: int) -> None:
    """Wake the parked runs that wait for this realtime cohort, once it is ready.

    Does nothing while the cohort still calculates. A run the CDP API confirms awake moves to queued.
    Raises after trying every run if any resume failed, so the caller retries; a second resume of the
    same run is a no-op.
    """
    cohort = Cohort.objects.filter(pk=cohort_id, team_id=team_id, deleted=False).select_related("team").first()
    if cohort is None or not realtime_cohort_is_ready(cohort):
        return
    waiting = HogFlowBatchJob.objects.filter(
        status=HogFlowBatchJobState.WAITING, team__project_id=cohort.team.project_id
    ).select_related("team", "hog_flow")
    errors: list[Exception] = []
    for job in waiting.iterator(chunk_size=500):
        # Each ready cohort scans the project's waiting runs, so a run that waits for another cohort is
        # skipped before any cohort query.
        filters = batch_job_audience_filters(job)
        if str(sole_audience_cohort_id(filters)) != str(cohort_id):
            continue
        # A cohort edit during this loop clears the readiness stamps, so each run checks a fresh load. The run
        # parked on this cohort, so an edit that drops its behavioral filters still resumes it once ready.
        fresh_cohort = Cohort.objects.filter(pk=cohort_id, team_id=team_id, deleted=False).first()
        if fresh_cohort is None or not realtime_cohort_is_ready(fresh_cohort):
            continue
        try:
            response = resume_hog_flow_batch_job(
                team_id=job.team_id, hog_flow_id=str(job.hog_flow_id), batch_job_id=str(job.id)
            )
            outcome = str(response.json().get("outcome", f"http_{response.status_code}"))
        except Exception as error:
            REALTIME_COHORT_RESUMES.labels(outcome="error").inc()
            capture_exception(error)
            errors.append(error)
            continue
        REALTIME_COHORT_RESUMES.labels(outcome=outcome).inc()
        if outcome in ("resumed", "already_resumed"):
            HogFlowBatchJob.objects.filter(pk=job.pk, status=HogFlowBatchJobState.WAITING).update(
                status=HogFlowBatchJobState.QUEUED, updated_at=timezone.now()
            )
        elif outcome == "job_running" or response.status_code >= 500:
            # The resolver is busy or the API failed, so a later attempt can still wake the run.
            errors.append(RuntimeError(f"Batch run {job.id} was not resumed: {outcome}"))
        else:
            logger.warning("realtime_cohort_resume_not_delivered", batch_job_id=str(job.id), outcome=outcome)
    if errors:
        raise errors[0]
