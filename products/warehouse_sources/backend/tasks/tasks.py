from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.ph_client import get_client
from posthog.scoping_audit import skip_team_scope_audit

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_DELETED_JOB_ERROR,
    SYNC_DISABLED_JOB_ERROR,
    ExternalDataSchema,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable

logger = structlog.get_logger(__name__)

# Bounds the teardown-task fanout of one sweep tick; the remainder drains on later ticks.
STOPPED_SYNC_SWEEP_CAP = 500

# A schema saved within this window may have been auto-disabled by its own workflow's
# failure handling, which the write-time dispatch excludes from cancellation; sweeping it
# this tick would cancel that still-finishing workflow. `updated_at` only bumps on
# `save()`, so bulk `.update()` disables are not delayed.
STOPPED_SYNC_SWEEP_GRACE = timedelta(minutes=30)

# Jobs stuck in Running from before this sweep shipped are left alone rather than
# mass-failed (and their latest_error rewritten) on the first ticks after deploy.
STOPPED_SYNC_SWEEP_MAX_JOB_AGE = timedelta(days=7)


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=10,
)
@skip_team_scope_audit
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

    # A dispatch can go stale: if the schema was re-enabled before this task (or one
    # of its retries) ran, tearing down now would kill the new legitimate run.
    if (
        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id, should_sync=True)
        .exclude(deleted=True)
        .exists()
    ):
        logger.info(
            "cleanup_disabled_external_data_schema_skipped_syncing_again",
            team_id=team_id,
            external_data_schema_id=schema_id,
        )
        return

    teardown_schema_syncs(
        team_id=team_id,
        schema_id=schema_id,
        reason=reason,
        exclude_workflow_id=exclude_workflow_id,
    )


@shared_task(ignore_result=True)
@skip_team_scope_audit
def sweep_stopped_schema_syncs() -> None:
    """Backstop for the write-time disable/delete teardown dispatch.

    The model chokepoint is event-based, and events can be missed: a job created
    concurrently with the disable, a writer the chokepoint cannot see (bulk_update,
    raw SQL, a hard delete), or a dropped task. This sweep finds Running jobs whose
    schema no longer syncs and dispatches the same idempotent teardown, so a missed
    event heals on the next cycle instead of never. Overlap with a write-time
    dispatch still in flight is harmless for the same reason.
    """
    now = timezone.now()
    stopped = list(
        ExternalDataJob.objects.filter(status=ExternalDataJob.Status.RUNNING)
        .filter(Q(schema__should_sync=False) | Q(schema__deleted=True))
        .filter(created_at__gte=now - STOPPED_SYNC_SWEEP_MAX_JOB_AGE)
        .exclude(schema__updated_at__gte=now - STOPPED_SYNC_SWEEP_GRACE)
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


# Name pinned to where this task used to live in core: a rename would strand any message
# already queued under the old name across a deploy.
@shared_task(ignore_result=True, name="posthog.tasks.warehouse.validate_data_warehouse_table_columns")
@skip_team_scope_audit
def validate_data_warehouse_table_columns(team_id: int, table_id: str) -> None:
    ph_client = get_client()

    try:
        table = DataWarehouseTable.objects.get(team_id=team_id, id=table_id)
        columns = table.columns or {}
        for column in columns.keys():
            # Background validation is userless; validate table schema, not requester permissions.
            columns[column]["valid"] = table.validate_column_type(column, bypass_warehouse_access_control=True)
        table.columns = columns
        table.save()

        if ph_client:
            ph_client.capture(distinct_id=team_id, event="validate_data_warehouse_table_columns succeeded")
    except Exception as e:
        logger.exception(
            f"validate_data_warehouse_table_columns raised an exception for table: {table_id}",
            exc_info=e,
            team_id=team_id,
        )

        if ph_client:
            ph_client.capture(distinct_id=team_id, event="validate_data_warehouse_table_columns errored")
    finally:
        if ph_client:
            ph_client.shutdown()
