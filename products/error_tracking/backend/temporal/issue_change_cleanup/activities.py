import datetime
from uuid import UUID

from django.db import close_old_connections
from django.utils import timezone

import structlog
from temporalio import activity

from products.error_tracking.backend.models import ErrorTrackingIssueChange
from products.error_tracking.backend.temporal.issue_change_cleanup.types import (
    IssueChangeCleanupInputs,
    IssueChangeCleanupResult,
)

logger = structlog.get_logger(__name__)


@activity.defn
def cleanup_issue_changes_activity(inputs: IssueChangeCleanupInputs) -> IssueChangeCleanupResult:
    """Deletes issue changes older than the retention, dispatched or not.

    A change still undispatched after the retention is no longer news, and keeping it would let the
    table grow without bound while no dispatcher runs.
    """
    close_old_connections()

    cutoff = timezone.now() - datetime.timedelta(days=inputs.days_old)
    # Every team's rows, so the scoped manager does not apply.
    expired = ErrorTrackingIssueChange.objects.unscoped().filter(created_at__lt=cutoff).order_by("id")
    last_id: UUID | None = None
    deleted_count = 0
    while True:
        batch = expired if last_id is None else expired.filter(id__gt=last_id)
        batch_ids = list(batch.values_list("id", flat=True)[: inputs.batch_size])
        if not batch_ids:
            break
        # nosemgrep: idor-lookup-without-team (cross-team retention cleanup; ids are this run's expired rows)
        deleted, _ = ErrorTrackingIssueChange.objects.unscoped().filter(id__in=batch_ids).delete()
        deleted_count += deleted
        last_id = batch_ids[-1]
        if activity.in_activity():
            activity.heartbeat(deleted_count)

    logger.info(
        "error_tracking.issue_change_cleanup.complete",
        deleted_count=deleted_count,
        cutoff=cutoff.isoformat(),
    )
    return IssueChangeCleanupResult(deleted_count=deleted_count)
