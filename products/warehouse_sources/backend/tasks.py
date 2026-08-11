from django.db.models import Q

import structlog
from celery import shared_task

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_DELETED_JOB_ERROR,
    SYNC_DISABLED_JOB_ERROR,
)

logger = structlog.get_logger(__name__)

# Bounds the teardown-task fanout of one sweep tick; the remainder drains on later ticks.
STOPPED_SYNC_SWEEP_CAP = 500


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=10,
)
def cleanup_disabled_external_data_schema(
    *,
    team_id: int,
    schema_id: str,
    reason: str,
    exclude_workflow_id: str | None = None,
) -> None:
    """Stop in-flight sync work after a schema stopped syncing (disabled or deleted).

    Dispatched from the ``ExternalDataSchema`` write chokepoints via
    ``transaction.on_commit``. Runs asynchronously because the teardown talks to
    Temporal and may fail tens of thousands of queue batch rows, which must not
    block the API response that flipped the flag. Retries with backoff; every
    teardown step is idempotent, so a retry only re-runs what previously failed.
    """
    # Deferred: keeps the queue/Temporal stack out of Celery task autodiscovery.
    from products.warehouse_sources.backend.sync_teardown import teardown_schema_syncs  # noqa: PLC0415

    teardown_schema_syncs(
        team_id=team_id,
        schema_id=schema_id,
        reason=reason,
        exclude_workflow_id=exclude_workflow_id,
    )


@shared_task(ignore_result=True)
def sweep_stopped_schema_syncs() -> None:
    """Backstop for the write-time disable/delete teardown dispatch.

    The model chokepoint is event-based, and events can be missed: a job created
    concurrently with the disable, a writer the chokepoint cannot see (bulk_update,
    raw SQL, a hard delete), or a dropped task. This sweep finds Running jobs whose
    schema no longer syncs and dispatches the same idempotent teardown, so a missed
    event heals on the next cycle instead of never. Overlap with a write-time
    dispatch still in flight is harmless for the same reason.
    """
    stopped = list(
        ExternalDataJob.objects.filter(status=ExternalDataJob.Status.RUNNING)
        .filter(Q(schema__should_sync=False) | Q(schema__deleted=True))
        .values_list("schema_id", "team_id", "schema__deleted")
        .distinct()[: STOPPED_SYNC_SWEEP_CAP + 1]
    )
    if len(stopped) > STOPPED_SYNC_SWEEP_CAP:
        logger.warning("sweep_stopped_schema_syncs_capped", cap=STOPPED_SYNC_SWEEP_CAP)
        stopped = stopped[:STOPPED_SYNC_SWEEP_CAP]

    for schema_id, team_id, deleted in stopped:
        cleanup_disabled_external_data_schema.delay(
            team_id=team_id,
            schema_id=str(schema_id),
            reason=SCHEMA_DELETED_JOB_ERROR if deleted else SYNC_DISABLED_JOB_ERROR,
        )
    if stopped:
        logger.info("sweep_stopped_schema_syncs_dispatched", count=len(stopped))
