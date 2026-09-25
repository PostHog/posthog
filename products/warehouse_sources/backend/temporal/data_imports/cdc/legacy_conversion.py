"""One-time conversion of the state the retired legacy CDC lane left behind.

The legacy lane delivered some tables' changes from capture itself. It paused each such table's
schedule while it streamed, held a snapshotting table's changes as deferred runs in
`sync_type_config`, marked its source `cdc_ingest_mode: legacy`, and created job rows of its own.
Capture now only writes the S3 buffer, so it runs this before every read. Each step finds nothing
once the state it converts is gone, so this module can go once no source logs a conversion.

Every step that can fail raises before capture reads the WAL, so a failed conversion retries on the
next run with nothing written to the buffer in between. Starting a restarted snapshot is the one
exception: its table is already reset, so a failure there stays pending and the next run retries it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import psycopg
from structlog.types import FilteringBoundLogger

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    CDC_SNAPSHOT_LANE_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import purge_buffer_prefix
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import CDC_EXTRACTION_WORKFLOW_ID_PREFIX
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import BUFFER_LANE, cancel_running_sync
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import has_batches_in_flight
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import IngestMode, decode_job_inputs
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)

# Shown as latest_error on the capture job rows `_close_stranded_capture_jobs` fails.
STRANDED_CAPTURE_JOB_MESSAGE = (
    "CDC run ended without finalizing this job (worker timeout or eviction). It was superseded by a "
    "later run; no data was lost — change capture resumes from the last confirmed replication position."
)
# A healthy capture run queued its first batch within seconds, so a batch-less row older than this is
# abandoned, and one younger may still belong to a run that is finishing.
_STRANDED_JOB_MIN_AGE = dt.timedelta(minutes=30)
# Batches are pruned from the queue after 14 days, so "no batches" is only trustworthy inside that
# window. Older rows stay as they are, because an abandoned run looks the same as one whose batches aged out.
_STRANDED_JOB_MAX_AGE = dt.timedelta(days=14)
# Set by the reset that restarts a deferred-run table's snapshot, and cleared once its schedule runs
# again. The reset drops the deferred runs, so without it nothing would retry a failed schedule rebuild,
# and the new snapshot would never start.
_SCHEDULE_RESUME_PENDING_KEY = "cdc_schedule_resume_pending"


def convert_legacy_cdc_state(
    source: ExternalDataSource,
    schemas: Sequence[ExternalDataSchema],
    *,
    ingest_mode: IngestMode,
    logger: FilteringBoundLogger,
) -> None:
    """Convert whatever legacy state this source still carries. Raises on a failure that must retry."""
    if ingest_mode != "buffered":
        _convert_legacy_source(source, schemas, logger)
    for schema in schemas:
        config = schema.sync_type_config or {}
        if config.get("cdc_deferred_runs"):
            _restart_snapshot_in_buffer(schema, logger)
        elif config.get(_SCHEDULE_RESUME_PENDING_KEY):
            _start_restarted_snapshot(schema, logger)
    try:
        _close_stranded_capture_jobs(source, schemas, logger)
    except Exception:
        # Cosmetic: a stranded row only misreports a run that already ended.
        logger.warning("cdc_stranded_capture_jobs_close_failed", exc_info=True)


def _convert_legacy_source(
    source: ExternalDataSource, schemas: Sequence[ExternalDataSchema], logger: FilteringBoundLogger
) -> None:
    """Move a source whose changes the legacy lane still delivered onto the buffer.

    Its buffer holds only copies of changes the legacy lane already delivered, so it is emptied
    before capture writes the first file. What capture reads next continues from the slot's
    position, which legacy delivery already reached. The legacy lane paused the schedule of every
    streaming table because capture delivered its changes. That schedule is now the table's
    consumer, so it is rebuilt. Legacy batches still in the load queue land first, because the
    consumer stands down while any are in flight.
    """
    all_cdc_schema_ids = list(
        ExternalDataSchema.objects.filter(
            team_id=source.team_id, source_id=source.id, sync_type=ExternalDataSchema.SyncType.CDC
        )
        .exclude(deleted=True)
        .values_list("id", flat=True)
    )
    for schema_id in all_cdc_schema_ids:
        purge_buffer_prefix(source.team_id, str(schema_id), logger, strict=True)
    for schema in schemas:
        _resume_schedule(schema, trigger=False)

    # Written last, so a failure above repeats the whole conversion. A repeat is safe because the run
    # fails before it reads the WAL, so the buffer has gained nothing a second purge would drop.
    # A queryset update, not `source.save()`, whose activity-log diff walks the source's whole job history.
    source.job_inputs = {**decode_job_inputs(source.job_inputs), "cdc_ingest_mode": "buffered"}
    ExternalDataSource.objects.filter(id=source.id, team_id=source.team_id).update(
        job_inputs=source.job_inputs, updated_at=dt.datetime.now(dt.UTC)
    )
    logger.info("cdc_legacy_source_converted", schemas=len(all_cdc_schema_ids))


def _restart_snapshot_in_buffer(schema: ExternalDataSchema, logger: FilteringBoundLogger) -> None:
    """Re-snapshot a table the legacy lane still held deferred runs for.

    Nothing merges deferred runs anymore, so the table snapshots again in the buffer. Its old sync must
    stop first, because one that hands over after the reset flips the table to streaming without those
    changes. Until it stops, the schedule stays paused and capture leaves the table out.
    """
    # data_load.service imports temporalio at module scope; deferred to keep the Temporal client off
    # this module's import path, as capture's other schedule calls do.
    from products.data_warehouse.backend.facade.api import pause_external_data_schedule  # noqa: PLC0415

    pause_external_data_schedule(str(schema.id))
    stopping = cancel_running_sync(schema)
    if stopping is not None or has_batches_in_flight(schema):
        logger.info("cdc_legacy_snapshot_restart_waiting", schema_id=str(schema.id), stopping_workflow_id=stopping)
        return

    deferred_runs = len(schema.sync_type_config.get("cdc_deferred_runs") or [])
    purge_buffer_prefix(schema.team_id, str(schema.id), logger, strict=True)
    schema.sync_type_config = update_sync_type_config_keys(
        schema.id,
        schema.team_id,
        updates={
            "cdc_mode": "snapshot",
            "reset_pipeline": True,
            CDC_SNAPSHOT_LANE_KEY: BUFFER_LANE,
            _SCHEDULE_RESUME_PENDING_KEY: True,
        },
        removes=["cdc_deferred_runs", "cdc_last_log_position"],
        extra_model_fields={"initial_sync_complete": False},
    )
    schema.initial_sync_complete = False
    logger.info("cdc_legacy_snapshot_restarted_in_buffer", schema_id=str(schema.id), deferred_runs=deferred_runs)
    _start_restarted_snapshot(schema, logger)


def _start_restarted_snapshot(schema: ExternalDataSchema, logger: FilteringBoundLogger) -> None:
    """Rebuild the paused schedule and start the new snapshot.

    A failed or skipped rebuild stays pending for the next capture run. The restart paused this
    schedule itself, so nothing else starts the snapshot once a deliberate hold lifts.
    """
    try:
        resumed = _resume_schedule(schema, trigger=True)
    except Exception:
        logger.exception("cdc_legacy_snapshot_schedule_resume_failed", schema_id=str(schema.id))
        return
    if not resumed:
        return
    schema.sync_type_config = update_sync_type_config_keys(
        schema.id, schema.team_id, removes=[_SCHEDULE_RESUME_PENDING_KEY]
    )


def _resume_schedule(schema: ExternalDataSchema, *, trigger: bool) -> bool:
    """Rebuild the table's schedule unpaused, and create it if it is missing. Returns whether it did.

    A plain unpause does nothing to a missing schedule. Skipped where the pause is deliberate: a
    schema whose status is Paused, an admin-triggered run that holds the schedule until it finishes,
    and a broken source that waits for Repair CDC, which unpauses it. A
    capture pause is not checked, because capture is running, so that pause is over. A schema with
    no sync frequency is skipped because the schedule builder cannot turn a null interval into a
    cadence.
    """
    # See `_restart_snapshot_in_buffer` for why this import is deferred.
    from products.data_warehouse.backend.facade.api import sync_external_data_job_workflow  # noqa: PLC0415

    config = schema.sync_type_config or {}
    if (
        schema.status == ExternalDataSchema.Status.PAUSED
        or config.get("cdc_broken")
        or config.get("admin_unpause_schedule_after_run")
        or schema.sync_frequency_interval is None
    ):
        return False
    sync_external_data_job_workflow(schema, create=True, should_sync=True, trigger_immediately=trigger)
    return True


def _close_stranded_capture_jobs(
    source: ExternalDataSource, schemas: Sequence[ExternalDataSchema], logger: FilteringBoundLogger
) -> None:
    """Fail RUNNING job rows the legacy lane's capture runs left behind.

    Legacy capture created one per written table and closed it when the run finished. A run that died
    mid-way left its row RUNNING. A row with batches in the queue belongs to the loader, which closes
    it. A row without any has no outstanding work, so failing it cannot race a late load. Scoped to
    capture's own workflow ids, so a table's scheduled sync is never touched.
    """
    now = dt.datetime.now(tz=dt.UTC)
    stranded = list(
        ExternalDataJob.objects.filter(
            team_id=source.team_id,
            schema_id__in=[s.id for s in schemas],
            status=ExternalDataJob.Status.RUNNING,
            workflow_id__startswith=CDC_EXTRACTION_WORKFLOW_ID_PREFIX,
            created_at__gt=now - _STRANDED_JOB_MAX_AGE,
            created_at__lt=now - _STRANDED_JOB_MIN_AGE,
        ).order_by("created_at")[:200]
    )
    if not stranded:
        return

    closed = 0
    conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    try:
        for job in stranded:
            if BatchQueue.count_batches_for_run(conn, job_id=str(job.id)) > 0:
                continue
            job.status = ExternalDataJob.Status.FAILED
            job.latest_error = STRANDED_CAPTURE_JOB_MESSAGE
            job.finished_at = now
            job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
            closed += 1
    finally:
        conn.close()
    if closed:
        logger.info("cdc_stranded_capture_jobs_closed", count=closed)
