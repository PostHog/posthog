from datetime import timedelta

from django.db.models import DateTimeField, ExpressionWrapper, F, Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEMA_DELETED_JOB_ERROR,
    SYNC_DISABLED_JOB_ERROR,
    ExternalDataSchema,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

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


# Bounds the Temporal fanout of one reconcile tick; the remainder drains on later ticks.
DRIFTED_SCHEDULE_SWEEP_CAP = 500

# Match the query-time staleness warning: a schema is drifted only once its last sync is older
# than twice its configured interval, so a run merely overdue by one cycle is left alone.
STALE_SYNC_MULTIPLIER = 2


@shared_task(ignore_result=True)
@skip_team_scope_audit
def reconcile_drifted_schema_schedules() -> None:
    """Re-issue Temporal schedules for schemas that should sync but silently stopped.

    ``should_sync`` in Postgres and the Temporal schedule are written separately, so a schema can
    sit with ``should_sync=True`` behind a paused or missing schedule and no error on any surface —
    the table just stops updating. This sweep finds enabled, non-deleted schemas whose last sync is
    more than twice their interval old and rebuilds each drifted schedule (unpausing a paused one,
    creating a missing one) with a catch-up run.

    Scope keeps the sweep to genuine silent drift:
    - CDC schemas pause their per-schema schedule by design while streaming, so they are excluded.
    - Direct-query sources have no schedule to reconcile.
    - Schemas an admin paused on purpose carry ``admin_unpause_schedule_after_run``; leave them.
    - Only ``Completed``/``Running`` schemas qualify — ``Failed`` and billing-limited states are
      already surfaced and re-issuing would not help them.
    """
    # Deferred: pulls the Temporal client stack, kept out of Celery task autodiscovery.
    from products.data_warehouse.backend.facade.api import bulk_reconcile_external_data_schedules  # noqa: PLC0415

    now = timezone.now()
    # Drifted once now is past last_synced_at + STALE_SYNC_MULTIPLIER * interval.
    stale_after = ExpressionWrapper(
        F("last_synced_at") + F("sync_frequency_interval") * STALE_SYNC_MULTIPLIER,
        output_field=DateTimeField(),
    )
    drifted = list(
        ExternalDataSchema.objects.select_related("source")
        .filter(
            should_sync=True,
            deleted=False,
            last_synced_at__isnull=False,
            sync_frequency_interval__isnull=False,
            status__in=[ExternalDataSchema.Status.COMPLETED, ExternalDataSchema.Status.RUNNING],
        )
        .exclude(sync_type=ExternalDataSchema.SyncType.CDC)
        .exclude(source__access_method=ExternalDataSource.AccessMethod.DIRECT)
        # `__contains` (jsonb @>) so a schema missing the key stays a candidate — an equality
        # exclude would drop it, since the absent key compares as SQL NULL.
        .exclude(sync_type_config__contains={"admin_unpause_schedule_after_run": True})
        .annotate(stale_after=stale_after)
        .filter(stale_after__lt=now)
        .order_by("stale_after")[: DRIFTED_SCHEDULE_SWEEP_CAP + 1]
    )
    if len(drifted) > DRIFTED_SCHEDULE_SWEEP_CAP:
        logger.warning("reconcile_drifted_schema_schedules_capped", cap=DRIFTED_SCHEDULE_SWEEP_CAP)
        drifted = drifted[:DRIFTED_SCHEDULE_SWEEP_CAP]

    if not drifted:
        return

    result = bulk_reconcile_external_data_schedules(drifted)
    for schema_id, exc in result.failures:
        logger.exception("reconcile_drifted_schema_schedule_failed", external_data_schema_id=schema_id, exc_info=exc)
    logger.info(
        "reconcile_drifted_schema_schedules_done",
        candidates=len(drifted),
        created=len(result.created),
        resumed=len(result.resumed),
        skipped_active=len(result.skipped_active),
        failed=len(result.failures),
    )
