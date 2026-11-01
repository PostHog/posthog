"""Resolve a batch run's person audience once, store it, and page the stored result for the resolver."""

from itertools import batched
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

import structlog
from rest_framework import exceptions

from posthog.dataclasses import frozen
from posthog.errors import ClickHouseQueryTimeOut
from posthog.exceptions_capture import capture_exception

from products.feature_flags.backend.person_sampling import bounded_memory_settings
from products.workflows.backend.facade.contracts import AudiencePage, WorkflowBatchJobNotFound
from products.workflows.backend.facade.enums import HogFlowBatchJobAudienceStatus, HogFlowBatchJobState
from products.workflows.backend.models.hog_flow_batch_job import HogFlowBatchJob, HogFlowBatchJobAudienceMember
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import batch_job_audience_filters
from products.workflows.backend.services.batch_audience import (
    get_batch_audience_person_ids_snapshot,
    person_audience_page_size,
)

logger = structlog.get_logger(__name__)

# One scan of the person table for the whole audience; the cohort calculator runs the same shape under this cap.
AUDIENCE_SNAPSHOT_QUERY_TIMEOUT_SECONDS = 1200
AUDIENCE_SNAPSHOT_WRITE_CHUNK = 5000

TERMINAL_STATES = {HogFlowBatchJobState.COMPLETED, HogFlowBatchJobState.FAILED, HogFlowBatchJobState.CANCELLED}


@frozen
class AudienceSnapshotStatus:
    status: HogFlowBatchJobAudienceStatus
    audience_size: int | None
    error: str | None


def _snapshot_status(job: HogFlowBatchJob) -> AudienceSnapshotStatus:
    if job.audience_status is None:
        raise ValueError(f"Batch run {job.id} has no audience snapshot")
    return AudienceSnapshotStatus(
        status=HogFlowBatchJobAudienceStatus(job.audience_status),
        audience_size=job.audience_size,
        error=job.audience_error,
    )


def request_audience_snapshot(
    *, team_id: int, batch_job_id: str, dedupe_key: str | None, max_audience_size: int
) -> AudienceSnapshotStatus:
    """Start resolving the run's audience, once. Later calls report where the resolution got to."""
    try:
        job = HogFlowBatchJob.objects.get(id=batch_job_id, team_id=team_id)
    except (HogFlowBatchJob.DoesNotExist, DjangoValidationError, ValueError):
        # DjangoValidationError fires when the id is not a parseable UUID.
        raise WorkflowBatchJobNotFound()
    if job.audience_status is not None:
        return _snapshot_status(job)
    # The resolver can ask again after a crash mid-request. Only the call that claims the row enqueues the task.
    claimed = HogFlowBatchJob.objects.filter(pk=job.pk, audience_status__isnull=True).update(
        audience_status=HogFlowBatchJobAudienceStatus.RESOLVING, updated_at=timezone.now()
    )
    if not claimed:
        job.refresh_from_db()
        return _snapshot_status(job)
    from products.workflows.backend.tasks.batch_jobs import (  # noqa: PLC0415 — the task module imports this service
        resolve_batch_job_audience_snapshot,
    )

    try:
        resolve_batch_job_audience_snapshot.delay(team_id, str(job.id), dedupe_key, max_audience_size)
    except Exception:
        # Nothing will resolve the audience, so release the claim and let the resolver's next request try again.
        HogFlowBatchJob.objects.filter(pk=job.pk, audience_status=HogFlowBatchJobAudienceStatus.RESOLVING).update(
            audience_status=None, updated_at=timezone.now()
        )
        raise
    return AudienceSnapshotStatus(status=HogFlowBatchJobAudienceStatus.RESOLVING, audience_size=None, error=None)


def audience_failure_reason(error: Exception) -> str:
    """The reason the batch run's log stream shows. Internals stay out of it; a filter problem names itself."""
    if isinstance(error, ClickHouseQueryTimeOut):
        minutes = AUDIENCE_SNAPSHOT_QUERY_TIMEOUT_SECONDS // 60
        return (
            f"Audience query timed out after {minutes} minutes. "
            "Use fewer or simpler audience filters, or a smaller audience."
        )
    if isinstance(error, exceptions.ValidationError):
        return f"Audience filters can't be evaluated: {' '.join(_validation_messages(error.detail))}"
    return "Audience query failed"


def _validation_messages(detail: object) -> list[str]:
    """The plain messages inside DRF's nested error detail, without the field keys and codes."""
    if isinstance(detail, dict):
        return [message for value in detail.values() for message in _validation_messages(value)]
    if isinstance(detail, list):
        return [message for value in detail for message in _validation_messages(value)]
    return [str(detail)]


def resolve_audience_snapshot(
    *, team_id: int, batch_job_id: str, dedupe_key: str | None, max_audience_size: int
) -> None:
    """Run the audience query once and store every person id, then mark the run's audience ready or failed."""
    job = HogFlowBatchJob.objects.filter(id=batch_job_id, team_id=team_id).select_related("team", "hog_flow").first()
    if job is None or job.status in TERMINAL_STATES or job.audience_status == HogFlowBatchJobAudienceStatus.READY:
        return
    query_settings = bounded_memory_settings()
    query_settings.max_execution_time = AUDIENCE_SNAPSHOT_QUERY_TIMEOUT_SECONDS
    try:
        person_ids = get_batch_audience_person_ids_snapshot(
            job.team,
            batch_job_audience_filters(job),
            dedupe_key=dedupe_key,
            # One past the cap, so the resolver still sees the audience overflow and warns about it.
            limit=max_audience_size + 1,
            settings=query_settings,
        )
        _replace_audience_members(job, person_ids)
    except Exception as error:
        logger.exception("batch_audience_snapshot_failed", batch_job_id=str(job.id), team_id=team_id, error=str(error))
        capture_exception(error)
        HogFlowBatchJob.objects.filter(pk=job.pk).update(
            audience_status=HogFlowBatchJobAudienceStatus.FAILED,
            audience_error=audience_failure_reason(error),
            updated_at=timezone.now(),
        )
        return
    still_running = (
        HogFlowBatchJob.objects.filter(pk=job.pk)
        .exclude(status__in=TERMINAL_STATES)
        .update(
            audience_status=HogFlowBatchJobAudienceStatus.READY,
            audience_size=len(person_ids),
            audience_error=None,
            updated_at=timezone.now(),
        )
    )
    if not still_running:
        # The run ended while the query ran, and its cleanup already passed.
        delete_audience_snapshot(team_id=job.team_id, batch_job_id=str(job.id))


def _replace_audience_members(job: HogFlowBatchJob, person_ids: list[str]) -> None:
    delete_audience_snapshot(team_id=job.team_id, batch_job_id=str(job.id))
    for chunk in batched(person_ids, AUDIENCE_SNAPSHOT_WRITE_CHUNK, strict=False):
        HogFlowBatchJobAudienceMember.objects.for_team(job.team_id).bulk_create(
            [
                HogFlowBatchJobAudienceMember(batch_job_id=job.id, team_id=job.team_id, person_id=UUID(person_id))
                for person_id in chunk
            ]
        )


def get_audience_snapshot_page(*, team_id: int, batch_job_id: str, cursor: str | None) -> AudiencePage:
    """One page of the stored audience, in person id order, so the resolver pages it like the live query."""
    page_size = person_audience_page_size()
    members = HogFlowBatchJobAudienceMember.objects.for_team(team_id).filter(batch_job_id=UUID(batch_job_id))
    if cursor:
        members = members.filter(person_id__gt=UUID(cursor))
    ids = [
        str(person_id) for person_id in members.order_by("person_id").values_list("person_id", flat=True)[:page_size]
    ]
    return AudiencePage(ids=ids, has_more=len(ids) == page_size)


def delete_audience_snapshot(*, team_id: int, batch_job_id: str) -> None:
    members = HogFlowBatchJobAudienceMember.objects.for_team(team_id).filter(batch_job_id=batch_job_id)
    while ids := list(members.values_list("id", flat=True)[:AUDIENCE_SNAPSHOT_WRITE_CHUNK]):
        members.filter(id__in=ids).delete()
