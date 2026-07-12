"""CDC Temporal activities.

cdc_extract_activity: Core extraction — reads WAL, decodes, batches, writes to
S3 via pipeline, and inserts batch notifications into the warehouse-sources
Postgres queue for streaming schemas. Snapshot schemas defer their batch
notifications to `sync_type_config["cdc_deferred_runs"]` until the schema
transitions to streaming.

validate_cdc_prerequisites_activity: Wraps prerequisite validator for Temporal.
"""

from __future__ import annotations

import time
import uuid
import typing
import datetime as dt
import dataclasses
from collections.abc import Callable

from django.db import close_old_connections

import psycopg
import pyarrow as pa
import structlog
import posthoganalytics
from temporalio import activity

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.activity_context import current_workflow_id, current_workflow_run_id
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import (
    cdc_supported_source_types,
    get_cdc_adapter,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    ChangeEventBatcher,
    build_scd2_table,
    deduplicate_table,
    enrich_delete_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.broken import mark_cdc_broken
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import (
    MAX_FRIENDLY_MESSAGE_LENGTH,
    CDCErrorCategory,
    CDCErrorInfo,
    CDCSchemaMergeError,
    classify_cdc_error,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import cdc_qualified_table_name
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import resolve_table_and_folder_names
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.kafka.common import SyncTypeLiteral
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer import S3BatchWriter
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _build_schema_snapshot,
)

logger = structlog.get_logger(__name__)

# Shown as latest_error on schemas reset by slot-invalidation recovery.
SLOT_INVALIDATION_RECOVERY_MESSAGE = (
    "The source database invalidated this source's replication slot (its WAL retention limit was "
    "exceeded), so changes since the last successful sync could not be read. PostHog recreated the "
    "slot and scheduled a full re-sync of this table; change data capture resumes automatically "
    "once the re-sync completes."
)

# The sweeper's auto-drop must fire below the engine's own retention cap, otherwise the
# engine invalidates the slot first and we lose the chance to act cleanly.
RETENTION_CAP_SAFETY_FACTOR = 0.8

# Mirrors maximum_attempts on CDCExtractionWorkflow's retry policy (workflows.py). On the final
# attempt a failure won't be retried, so it's the last chance to record a visible failed-run row.
CDC_MAX_EXTRACTION_ATTEMPTS = 3

# Shown as latest_error on prior-run jobs reconciled by _reconcile_orphaned_prior_jobs.
CDC_ORPHANED_JOB_MESSAGE = (
    "CDC run ended without finalizing this job (worker timeout or eviction). It was superseded by a "
    "later run; no data was lost — change capture resumes from the last confirmed replication position."
)
# Only reconcile prior RUNNING jobs older than this. A healthy run enqueues its first batch within
# seconds, so a no-batch job older than this is abandoned; the floor also keeps us clear of any
# concurrent manual/backfill run of the same source that has only just created its job row.
CDC_ORPHAN_JOB_MIN_AGE = dt.timedelta(minutes=30)
# Upper bound: batches are pruned from the queue after PARTITION_PRUNING_INTERVAL (14 days), so a
# "no batches" verdict is only trustworthy within that window. Never touch older rows — we cannot
# tell an abandoned run from one whose batches simply aged out.
CDC_ORPHAN_JOB_MAX_AGE = dt.timedelta(days=14)

# Backpressure guard: past this age a skipped tick is a stuck load, not a slow one — well beyond
# the loader's recovery-sweep grace (300s) and retry backoffs, so it only trips when a run needs
# operator attention. Skips past it log at error level; the tick is still skipped (see
# _previous_load_still_pending for why we never auto-fail the pending run).
CDC_BACKPRESSURE_STUCK_AGE = dt.timedelta(hours=2)

# Per-peek bound on WAL changes. A large backlog is drained over several passes (and, if needed,
# several scheduled runs) instead of one unbounded read that risks the 2h activity timeout and
# re-decodes from the slot start on every retry. The slot advances after each pass, so the next
# peek resumes where this one stopped.
CDC_MAX_CHANGES_PER_READ = 100_000
# Ceiling for the adaptive growth below. The decoder's MAX_TX_BUFFER_EVENTS (500k) is the real
# bound on an oversized single transaction — it trips before the window doubles far past it — so
# this only needs a little headroom above that guard.
CDC_MAX_CHANGES_LIMIT_CAP = 800_000
# Stop starting new peeks past this wall-clock so the final flush + slot advance fit inside the
# activity's 2h start-to-close timeout (see CDCExtractionWorkflow). The remainder is picked up on
# the next scheduled run.
CDC_READ_SOFT_DEADLINE_SECONDS = 90 * 60
# Heartbeat at most this often while fetching WAL rows (the activity heartbeat timeout is 10m).
CDC_READ_HEARTBEAT_INTERVAL_SECONDS = 30.0


@dataclasses.dataclass
class CDCExtractInput:
    team_id: int
    source_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "source_id": str(self.source_id),
        }


@dataclasses.dataclass
class ValidateCDCPrerequisitesInput:
    team_id: int
    source_id: uuid.UUID
    management_mode: str
    tables: list[str]
    schema: str
    slot_name: str | None
    publication_name: str | None


@dataclasses.dataclass
class _WriteTracker:
    """Per-resource state reused across micro-batch flushes.

    Each (table × write_mode) combination produces ONE job with sequential S3
    batch files, matching the multi-batch pattern of pipeline V3.
    """

    table_name: str
    write_resource_name: str
    cdc_write_mode: str
    cdc_table_mode: str
    key_columns: list[str]
    job: ExternalDataJob
    s3_writer: S3BatchWriter
    run_uuid: str
    batch_results: list  # list[BatchWriteResult]
    batch_index: int = 0
    total_rows: int = 0


class CDCExtractActivity:
    """Object-oriented body of cdc_extract_activity.

    All shared state lives on the instance. ``run()`` orchestrates the high
    level steps; private methods implement individual phases.
    """

    def __init__(self, inputs: CDCExtractInput) -> None:
        self.inputs = inputs
        self.log: structlog.types.FilteringBoundLogger = logger.bind(
            team_id=inputs.team_id, source_id=str(inputs.source_id)
        )

        # Populated during run().
        self.source: ExternalDataSource | None = None
        self.cdc_schemas: list[ExternalDataSchema] = []
        self.schema_by_name: dict[str, ExternalDataSchema] = {}
        self.pk_columns_by_table: dict[str, list[str]] = {}
        # Missing entry = sync all columns; otherwise the set is the projection (always includes PKs).
        self.enabled_columns_by_table: dict[str, set[str]] = {}
        self.write_trackers: dict[str, _WriteTracker] = {}
        self.created_jobs: list[ExternalDataJob] = []
        self.adapter: typing.Any = None
        self.reader: typing.Any = None
        self.batcher: ChangeEventBatcher | None = None
        self.last_end_lsn: str | None = None
        self.last_confirmed_lsn: str | None = None
        # Transaction-boundary tracking for safe mid-run slot advances. All events of
        # one transaction share the same commit end LSN (position_serialized), so an LSN
        # change marks a fully-yielded transaction. We only ever micro-advance the slot
        # past transactions that are completely yielded — see _read_wal_loop.
        self.current_txn_lsn: str | None = None
        self.last_complete_txn_end_lsn: str | None = None
        self.event_count: int = 0
        self.all_table_names: set[str] = set()
        # Wall-clock start, set in run(); drives cdc_extraction_duration_seconds.
        self._run_started_at: float | None = None

    # ------------------------------------------------------------------
    # Logger helpers
    # ------------------------------------------------------------------
    def _schema_log(self, schema: ExternalDataSchema) -> structlog.types.FilteringBoundLogger:
        """Logger bound with per-schema `log_source_id` so lines route under the schema in the Syncs UI."""
        return self.log.bind(log_source_id=str(schema.id))

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------
    def _emit_run_duration(self, status: str) -> None:
        if self._run_started_at is None:
            return
        metrics.get_extraction_duration_metric(self.inputs.team_id, str(self.inputs.source_id), status).record(
            time.monotonic() - self._run_started_at
        )

    def _emit_deferred_runs_depth(self) -> None:
        """Set the per-source deferred-runs gauge to the current depth across all CDC schemas.

        A gauge re-exports its last value, so it must be refreshed whenever deferred runs are
        stored OR drained — otherwise it reads stale-high after a flush. Summed across schemas
        because the gauge is keyed by source, not schema.
        """
        depth = sum(len(s.sync_type_config.get("cdc_deferred_runs") or []) for s in self.cdc_schemas)
        metrics.get_deferred_runs_depth_metric(self.inputs.team_id, str(self.inputs.source_id)).set(depth)

    def _confirm_position(self, lsn: str) -> None:
        """Advance the replication slot, recording success/failure metrics."""
        source_id = str(self.inputs.source_id)
        try:
            self.reader.confirm_position(lsn)
        except Exception:
            metrics.get_slot_advance_failures_metric(self.inputs.team_id, source_id).add(1)
            raise
        metrics.get_slot_advance_metric(self.inputs.team_id, source_id).add(1)

    # ------------------------------------------------------------------
    # Schema fetching (kept as a method so tests can patch it on the class)
    # ------------------------------------------------------------------
    def _get_cdc_schemas(self) -> list[ExternalDataSchema]:
        """Get all active CDC schemas for the source."""
        return list(
            ExternalDataSchema.objects.filter(
                source=self.source,
                sync_type=ExternalDataSchema.SyncType.CDC,
                should_sync=True,
            ).exclude(deleted=True)
        )

    # ------------------------------------------------------------------
    # sync_type_config persistence (locked merge, see update_sync_type_config_keys)
    # ------------------------------------------------------------------
    def _update_schema_sync_type_config(
        self,
        schema: ExternalDataSchema,
        *,
        updates: dict[str, typing.Any] | None = None,
        removes: list[str] | None = None,
        mutate: Callable[[dict[str, typing.Any]], None] | None = None,
        extra_model_fields: dict[str, typing.Any] | None = None,
    ) -> None:
        """Persist a `sync_type_config` change through the locked-merge helper, then refresh the
        in-memory copy from the returned dict.

        Every `sync_type_config` write in this activity goes through here so the long-lived
        in-memory schema can't clobber a concurrent API PATCH (or another writer) — the merge
        re-reads the row under a lock instead of overwriting it wholesale.
        """
        schema.sync_type_config = update_sync_type_config_keys(
            schema.id,
            schema.team_id,
            updates=updates,
            removes=removes,
            mutate=mutate,
            extra_model_fields=extra_model_fields,
        )
        if extra_model_fields:
            for field, value in extra_model_fields.items():
                setattr(schema, field, value)

    # ------------------------------------------------------------------
    # Deferred run flushing
    # ------------------------------------------------------------------
    def _flush_deferred_runs(self, schema: ExternalDataSchema) -> None:
        """Insert deferred-run batch notifications into the warehouse-sources Postgres queue.

        Called when a schema has just transitioned to cdc_mode="streaming" and has
        entries in sync_type_config["cdc_deferred_runs"].
        """
        deferred_runs: list[dict] = schema.sync_type_config.get("cdc_deferred_runs", [])
        if not deferred_runs:
            return

        assert self.source is not None
        source = self.source
        log = self._schema_log(schema)

        log.info(
            "flushing_deferred_cdc_runs",
            schema_id=str(schema.id),
            deferred_count=len(deferred_runs),
        )

        for run_meta in deferred_runs:
            job_id = run_meta["job_id"]
            run_uuid = run_meta["run_uuid"]
            batch_results = run_meta.get("batch_results", [])
            total_batches = run_meta.get("total_batches", len(batch_results))
            total_rows = run_meta.get("total_rows", 0)

            producer = PostgresProducer(
                database_url=WAREHOUSE_SOURCES_DATABASE_URL,
                team_id=schema.team_id,
                job_id=job_id,
                schema_id=str(schema.id),
                source_id=str(source.id),
                # Fall back to `name` for entries persisted before resource_name was stored.
                resource_name=run_meta.get("resource_name", schema.name),
                sync_type=typing.cast(SyncTypeLiteral, "cdc"),
                run_uuid=run_uuid,
                logger=log,
                primary_keys=run_meta.get("primary_keys"),
                cdc_write_mode=run_meta.get("cdc_write_mode", "incremental_merge"),
                cdc_table_mode=run_meta.get("cdc_table_mode"),
                workflow_id=current_workflow_id(),
                workflow_run_id=current_workflow_run_id(),
                **self._partition_kwargs(schema),
            )

            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import (
                BatchWriteResult,
            )

            for i, br in enumerate(batch_results):
                is_final = i == len(batch_results) - 1
                result = BatchWriteResult(
                    s3_path=br["s3_path"],
                    row_count=br["row_count"],
                    byte_size=br["byte_size"],
                    batch_index=br["batch_index"],
                    timestamp_ns=br.get("timestamp_ns", 0),
                )
                producer.send_batch_notification(
                    batch_result=result,
                    is_final_batch=is_final,
                    total_batches=total_batches if is_final else None,
                    total_rows=total_rows if is_final else None,
                    data_folder=run_meta.get("data_folder"),
                    schema_path=run_meta.get("schema_path"),
                )

            try:
                producer.flush()
            finally:
                producer.close()

        self._update_schema_sync_type_config(schema, updates={"cdc_deferred_runs": []})
        self._emit_deferred_runs_depth()

        log.info("deferred_runs_flushed", schema_id=str(schema.id))

    # ------------------------------------------------------------------
    # Tracker creation
    # ------------------------------------------------------------------
    def _get_or_create_tracker(
        self,
        table_name: str,
        write_resource_name: str,
        cdc_write_mode: str,
        cdc_table_mode: str,
        key_columns: list[str],
        schema: ExternalDataSchema,
    ) -> _WriteTracker:
        tracker = self.write_trackers.get(write_resource_name)
        if tracker is not None:
            return tracker

        # Stash `cdc_write_mode` alongside the schema snapshot so the Syncs UI can distinguish
        # the two ExternalDataJob rows produced when `cdc_table_mode='both'` — no extra column.
        schema_snapshot = _build_schema_snapshot(schema)
        schema_snapshot["cdc_write_mode"] = cdc_write_mode

        job = ExternalDataJob.objects.create(
            team_id=self.inputs.team_id,
            pipeline_id=self.inputs.source_id,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
            pipeline_version=ExternalDataJob.PipelineVersion.V3,
            schema_snapshot=schema_snapshot,
        )
        self.created_jobs.append(job)

        run_uuid = str(uuid.uuid4())
        s3_writer = S3BatchWriter(
            logger=self.log,
            job=job,
            schema_id=str(schema.id),
            run_uuid=run_uuid,
        )

        tracker = _WriteTracker(
            table_name=table_name,
            write_resource_name=write_resource_name,
            cdc_write_mode=cdc_write_mode,
            cdc_table_mode=cdc_table_mode,
            key_columns=key_columns,
            job=job,
            s3_writer=s3_writer,
            run_uuid=run_uuid,
            batch_results=[],
        )
        self.write_trackers[write_resource_name] = tracker
        return tracker

    # ------------------------------------------------------------------
    # Batch notification dispatch & deferred persistence
    # ------------------------------------------------------------------
    def _send_batch_notification(
        self,
        tracker: _WriteTracker,
        batch_result: typing.Any,
        is_final_batch: bool,
    ) -> None:
        """Insert a batch notification into the warehouse-sources Postgres queue for a streaming tracker."""
        assert self.source is not None
        schema = self.schema_by_name[tracker.table_name]
        producer = PostgresProducer(
            database_url=WAREHOUSE_SOURCES_DATABASE_URL,
            team_id=self.inputs.team_id,
            job_id=str(tracker.job.id),
            schema_id=str(schema.id),
            source_id=str(self.source.id),
            resource_name=tracker.write_resource_name,
            sync_type=typing.cast(SyncTypeLiteral, "cdc"),
            run_uuid=tracker.run_uuid,
            logger=self._schema_log(schema),
            primary_keys=tracker.key_columns or None,
            cdc_write_mode=tracker.cdc_write_mode,
            cdc_table_mode=tracker.cdc_table_mode,
            workflow_id=current_workflow_id(),
            workflow_run_id=current_workflow_run_id(),
            **self._partition_kwargs(schema),
        )
        try:
            producer.send_batch_notification(
                batch_result=batch_result,
                is_final_batch=is_final_batch,
                total_batches=tracker.batch_index if is_final_batch else None,
                total_rows=tracker.total_rows if is_final_batch else None,
                data_folder=tracker.s3_writer.get_data_folder() if is_final_batch else None,
                schema_path=tracker.s3_writer.write_schema() if is_final_batch else None,
            )
            producer.flush()
        finally:
            # PostgresProducer holds an open psycopg connection — close per call so we don't leak.
            producer.close()

    def _store_deferred_batch(
        self,
        tracker: _WriteTracker,
        batch_result: typing.Any,
        schema: ExternalDataSchema,
    ) -> None:
        """Persist a batch result into the tracker's deferred entry in sync_type_config.

        Creates the entry on first call (keyed by run_uuid), appends to it on
        subsequent calls. Persists immediately so progress survives process failures.

        The entry lookup + append runs inside the locked merge (see
        update_sync_type_config_keys) so an interleaved API PATCH can't drop the
        deferred runs this activity is accumulating — read-modify-write on a stale
        copy is exactly the lost update the merge prevents.
        """

        def _append_batch(config: dict[str, typing.Any]) -> None:
            deferred = config.setdefault("cdc_deferred_runs", [])
            entry: dict | None = next((d for d in deferred if d.get("run_uuid") == tracker.run_uuid), None)

            if entry is None:
                entry = {
                    "job_id": str(tracker.job.id),
                    "run_uuid": tracker.run_uuid,
                    # Replayed by the deferred flush so it targets the same Delta table this batch went to.
                    "resource_name": tracker.write_resource_name,
                    "data_folder": tracker.s3_writer.get_data_folder(),
                    "schema_path": None,  # written on finalization
                    "total_batches": 0,
                    "total_rows": 0,
                    "primary_keys": tracker.key_columns or None,
                    "cdc_write_mode": tracker.cdc_write_mode,
                    "cdc_table_mode": tracker.cdc_table_mode,
                    "batch_results": [],
                }
                deferred.append(entry)

            entry["batch_results"].append(
                {
                    "s3_path": batch_result.s3_path,
                    "row_count": batch_result.row_count,
                    "byte_size": batch_result.byte_size,
                    "batch_index": batch_result.batch_index,
                    "timestamp_ns": batch_result.timestamp_ns,
                }
            )
            entry["total_batches"] = tracker.batch_index
            entry["total_rows"] = tracker.total_rows

        self._update_schema_sync_type_config(schema, mutate=_append_batch)
        self._emit_deferred_runs_depth()

        self._schema_log(schema).info(
            "cdc_deferred_run_stored",
            resource=tracker.write_resource_name,
            run_uuid=tracker.run_uuid,
            batch_index=batch_result.batch_index,
            total_batches=tracker.batch_index,
            total_rows=tracker.total_rows,
        )

    def _persist_deferred_finalization(
        self, schema: ExternalDataSchema, tracker: _WriteTracker, schema_path: str
    ) -> None:
        """Stamp the final schema_path + totals onto the tracker's deferred entry under the merge lock."""

        def _finalize(config: dict[str, typing.Any]) -> None:
            for entry in config.get("cdc_deferred_runs", []):
                if entry.get("run_uuid") == tracker.run_uuid:
                    entry["schema_path"] = schema_path
                    entry["total_batches"] = tracker.batch_index
                    entry["total_rows"] = tracker.total_rows
                    break

        self._update_schema_sync_type_config(schema, mutate=_finalize)

    # ------------------------------------------------------------------
    # Storage naming
    # ------------------------------------------------------------------
    def _consolidated_resource_name(self, schema: ExternalDataSchema) -> str:
        """Storage name for the consolidated table — must match the snapshot pipeline's.

        The CDC stream must target the same folder, otherwise streamed changes
        land in a parallel Delta table no query reads. `name` and folder diverge
        for rows renamed bare→qualified (`name="public.users"`, folder `users`).
        """
        _table_storage_name, folder_name = resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name)
        return folder_name

    def _partition_kwargs(self, schema: ExternalDataSchema) -> dict[str, typing.Any]:
        """Replay snapshot partitioning so CDC rows match the target Delta.

        Without this, partitioned targets silently drop CDC rows. No-op when unpartitioned.
        """
        if not schema.partitioning_enabled:
            return {}
        return {
            "partition_count": schema.partition_count,
            "partition_size": schema.partition_size,
            "partition_keys": schema.partitioning_keys,
            "partition_mode": schema.partition_mode,
            "partition_format": schema.partition_format,
        }

    # ------------------------------------------------------------------
    # Per-flush processing
    # ------------------------------------------------------------------
    def _process_flush(
        self,
        tables: dict[str, pa.Table],
        is_final: bool = False,
    ) -> set[str]:
        """Enrich, transform, write to S3, and dispatch one micro-batch.

        Streaming schemas: batch notification inserted into the Postgres queue immediately after each S3 write.
        Snapshot schemas: batch result persisted to sync_type_config immediately.

        Returns the set of write_resource_names that received data.
        """
        flushed: set[str] = set()
        events_extracted = 0

        for table_name, raw_table in tables.items():
            schema = self.schema_by_name.get(table_name)
            if schema is None:
                continue

            activity.heartbeat()

            # raw_table has one row per source change event (before SCD2/dedup fan-out).
            events_extracted += raw_table.num_rows

            key_columns = self.pk_columns_by_table.get(table_name, [])
            cdc_table_mode = schema.cdc_table_mode

            enriched_table = enrich_delete_rows(raw_table, key_columns)

            # Consolidated shares the snapshot's canonical folder; the `_cdc` companion is
            # CDC-only and stays self-consistent with its `name`-keyed snapshot seed.
            batch_writes: list[tuple[pa.Table, str, str]] = []
            if cdc_table_mode == "consolidated":
                consolidated_name = self._consolidated_resource_name(schema)
                batch_writes.append(
                    (deduplicate_table(enriched_table, key_columns), consolidated_name, "incremental_merge")
                )
            elif cdc_table_mode == "cdc_only":
                batch_writes.append(
                    (build_scd2_table(enriched_table, key_columns), f"{schema.name}_cdc", "scd2_append")
                )
            elif cdc_table_mode == "both":
                consolidated_name = self._consolidated_resource_name(schema)
                batch_writes.append(
                    (deduplicate_table(enriched_table, key_columns), consolidated_name, "incremental_merge")
                )
                batch_writes.append(
                    (build_scd2_table(enriched_table, key_columns), f"{schema.name}_cdc", "scd2_append")
                )

            for write_table, write_resource_name, cdc_write_mode in batch_writes:
                tracker = self._get_or_create_tracker(
                    table_name,
                    write_resource_name,
                    cdc_write_mode,
                    cdc_table_mode,
                    key_columns,
                    schema,
                )
                try:
                    batch_result = tracker.s3_writer.write_batch(write_table, batch_index=tracker.batch_index)
                except pa.ArrowTypeError as e:
                    # The per-batch table is built consistently (typed columns + safe fallback),
                    # so an Arrow type error here is a cross-batch merge conflict — a column whose
                    # type genuinely drifted mid-stream. Replaying re-fails identically, so surface
                    # it as non-retryable instead of looping the schedule.
                    raise CDCSchemaMergeError(
                        f"Incompatible column types across CDC batches for {write_resource_name}"
                    ) from e
                tracker.batch_results.append(batch_result)
                tracker.batch_index += 1
                tracker.total_rows += write_table.num_rows
                flushed.add(write_resource_name)

                self._schema_log(schema).info(
                    "cdc_batch_written",
                    table=table_name,
                    resource=write_resource_name,
                    rows=write_table.num_rows,
                    batch_index=tracker.batch_index - 1,
                    s3_path=batch_result.s3_path,
                )

                # Dispatch immediately so progress survives process failures.
                if schema.cdc_mode == "streaming":
                    self._send_batch_notification(tracker, batch_result, is_final_batch=is_final)
                elif schema.cdc_mode == "snapshot":
                    self._store_deferred_batch(tracker, batch_result, schema)

        if events_extracted:
            metrics.get_events_extracted_metric(self.inputs.team_id, str(self.inputs.source_id)).add(events_extracted)

        return flushed

    # ------------------------------------------------------------------
    # Top-level orchestration
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Core CDC extraction.

        1. Connect to source PG, read all pending WAL changes
        2. Decode and batch by table
        3. For each CDC schema:
           - Flush deferred runs if transitioning from snapshot → streaming
           - Write new events to S3
           - Insert batch notification into the warehouse-sources Postgres queue (streaming)
             or persist into sync_type_config (snapshot)
        4. Advance slot position
        5. Update cdc_last_log_position per schema
        """
        close_old_connections()
        self._run_started_at = time.monotonic()
        self.log.info("cdc_extract_started")

        if not self._setup():
            return

        if self._previous_load_still_pending():
            return

        self._mark_schemas_running()
        # Best-effort — must never break the extraction run, so guard the call
        # site: the method itself has unguarded lines (activity.info(),
        # conn.close()) and runs before the main try block below.
        try:
            self._reconcile_orphaned_prior_jobs()
        except Exception:
            self.log.warning("cdc_orphan_reconcile_unexpected_failed", exc_info=True)

        try:
            self.reader.connect()

            self._load_pk_columns()
            self._read_wal_loop()

            self.log.info("wal_changes_read", event_count=self.event_count, tables=list(self.all_table_names))

            self._handle_pk_changes_post_wal()
            truncated_tables = self._handle_truncates()

            if self.event_count == 0:
                self._handle_no_changes(truncated_tables)
                return

            self._flush_pending_deferred_runs()
            final_flushed = self._final_flush()
            self._finalize_trackers(final_flushed)
            self._advance_slot_after_run()
            self._update_log_positions()

        except Exception as exc:
            if self.adapter is not None and self.adapter.is_slot_invalidation_error(exc):
                try:
                    self._recover_from_slot_invalidation(exc)
                    self._emit_run_duration("recovered")
                    return
                except Exception as recovery_exc:
                    self.log.exception("cdc_slot_recovery_failed")
                    self._fail(recovery_exc)
            self._fail(exc)
        finally:
            if self.reader is not None:
                self.reader.close()

        self._finalize_success()
        self.log.info("cdc_extract_completed", event_count=self.event_count)

    # ------------------------------------------------------------------
    # Setup phase
    # ------------------------------------------------------------------
    def _setup(self) -> bool:
        """Load source + schemas + adapter. Returns False if there's nothing to do.

        Self-cleans the Temporal schedule if the source is deleted or has no
        active CDC schemas — otherwise the workflow keeps firing forever.
        """
        try:
            self.source = ExternalDataSource.objects.get(pk=self.inputs.source_id)
        except ExternalDataSource.DoesNotExist:
            self.log.info("source_not_found_deleting_schedule")
            self._delete_own_schedule()
            return False

        if self.source.deleted:
            self.log.info("source_soft_deleted_deleting_schedule")
            self._delete_own_schedule()
            return False

        self.cdc_schemas = self._get_cdc_schemas()
        if not self.cdc_schemas:
            self.log.info("no_active_cdc_schemas_deleting_schedule")
            self._delete_own_schedule()
            return False

        self.schema_by_name = {s.name: s for s in self.cdc_schemas}
        self.adapter = get_cdc_adapter(self.source)
        self.reader = self.adapter.create_reader(self.source)
        return True

    def _delete_own_schedule(self) -> None:
        try:
            from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

            delete_cdc_extraction_schedule(str(self.inputs.source_id))
        except Exception:
            self.log.exception("failed_to_delete_own_schedule")

    def _previous_load_still_pending(self) -> bool:
        """Backpressure guard: skip this tick while a previous run's batches are still loading.

        CDC ticks don't hold the per-schema pipeline lock the way external-data-job runs do,
        so without this check every tick enqueues a fresh run regardless of whether the
        previous one landed. Coexisting runs of one schema can then be claimed out of order
        by the loader (its head-of-line gate is run-scoped), and an incremental merge applied
        out of order silently overwrites newer rows with older ones. Skipping keeps at most
        one active run per schema; nothing has been peeked and the slot is untouched, so WAL
        accumulates and the next tick catches up.

        Per-source, not per-schema: the slot is read once for all tables, so one table's
        pending load must hold back the whole source's tick.

        Deliberately no auto-remediation past CDC_BACKPRESSURE_STUCK_AGE: the slot already
        advanced past the pending runs' events, so failing their batches would leave a
        permanent gap in the table. The queue-freshness alert fires well before the
        threshold, and if nobody intervenes the engine eventually invalidates the slot,
        which triggers the existing full re-sync recovery. Fail-open on probe errors — the
        producer writes to the same DB, so a run that can't be probed can't enqueue either.
        """
        schema_ids = [str(s.id) for s in self.cdc_schemas]
        try:
            conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
        except Exception:
            self.log.warning("cdc_backpressure_probe_connect_failed", exc_info=True)
            return False
        try:
            age = BatchQueue.get_oldest_non_terminal_batch_age_seconds(
                conn, team_id=self.inputs.team_id, schema_ids=schema_ids
            )
        except Exception:
            self.log.warning("cdc_backpressure_probe_failed", exc_info=True)
            return False
        finally:
            conn.close()

        if age is None:
            return False

        stuck = age >= CDC_BACKPRESSURE_STUCK_AGE.total_seconds()
        log = self.log.error if stuck else self.log.info
        log("cdc_tick_skipped_pending_load", oldest_pending_age_seconds=round(age, 1), stuck=stuck)
        metrics.get_tick_skipped_metric(self.inputs.team_id, str(self.inputs.source_id), stuck).add(1)
        return True

    def _mark_schemas_running(self) -> None:
        """Mark CDC schemas as Running at the start."""
        for schema in self.cdc_schemas:
            schema.status = ExternalDataSchema.Status.RUNNING
            schema.save(update_fields=["status", "updated_at"])

    def _reconcile_orphaned_prior_jobs(self) -> None:
        """Finalize this source's prior RUNNING jobs that were stranded mid-run.

        A CDC run creates an ExternalDataJob at its first WAL event (RUNNING) and only
        finalizes it on clean completion (the loader, for streaming) or in its own failure
        handler. If an activity attempt dies abruptly — a heartbeat/start-to-close timeout
        or worker eviction — that finalizer never runs and the row is stranded RUNNING; every
        later run leaks another. Nothing in-process can close it, so the next run does.

        The schedule's SKIP overlap policy means any prior run (a different workflow_run_id)
        has already ended, so its still-RUNNING rows are safe to close. We only fail rows that
        enqueued NO queue batches: with nothing queued the loader has no outstanding work, so
        failing cannot race a late load. Rows that did enqueue batches are left to the loader,
        which owns their completion. Best-effort — must never break the extraction run.
        """
        current_run_id = activity.info().workflow_run_id
        now = dt.datetime.now(tz=dt.UTC)
        try:
            orphans = list(
                ExternalDataJob.objects.filter(
                    team_id=self.inputs.team_id,
                    schema_id__in=[s.id for s in self.cdc_schemas],
                    status=ExternalDataJob.Status.RUNNING,
                    pipeline_version=ExternalDataJob.PipelineVersion.V3,
                    created_at__gt=now - CDC_ORPHAN_JOB_MAX_AGE,
                    created_at__lt=now - CDC_ORPHAN_JOB_MIN_AGE,
                )
                .exclude(workflow_run_id=current_run_id)
                .order_by("created_at")[:200]
            )
        except Exception:
            self.log.warning("cdc_orphan_reconcile_query_failed", exc_info=True)
            return

        if not orphans:
            return

        try:
            conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
        except Exception:
            self.log.warning("cdc_orphan_reconcile_queue_connect_failed", exc_info=True)
            return

        reconciled = 0
        try:
            for job in orphans:
                try:
                    if BatchQueue.count_batches_for_run(conn, job_id=str(job.id)) > 0:
                        # The run enqueued batches; the loader owns their completion — leave it.
                        continue
                    job.status = ExternalDataJob.Status.FAILED
                    job.latest_error = CDC_ORPHANED_JOB_MESSAGE
                    job.finished_at = dt.datetime.now(tz=dt.UTC)
                    job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])
                    reconciled += 1
                except Exception:
                    self.log.warning("cdc_orphan_reconcile_job_failed", job_id=str(job.id), exc_info=True)
        finally:
            conn.close()

        if reconciled:
            self.log.info("cdc_orphaned_jobs_reconciled", count=reconciled)

    # ------------------------------------------------------------------
    # PK column loading
    # ------------------------------------------------------------------
    def _load_pk_columns(self) -> None:
        """Build PK map from schema metadata, falling back to information_schema."""
        assert self.source is not None
        cdc_table_names = {s.name for s in self.cdc_schemas}

        # Build PK map from schema metadata (stored at source creation)
        for schema in self.cdc_schemas:
            stored_pks = schema.sync_type_config.get("primary_key_columns", [])
            if stored_pks:
                self.pk_columns_by_table[schema.name] = stored_pks

        # Fall back to information_schema for any tables missing PKs
        missing_pk_tables = [t for t in cdc_table_names if t not in self.pk_columns_by_table]
        if missing_pk_tables:
            db_schema = (self.source.job_inputs or {}).get("schema", "public")
            queried_pks = self.reader.get_primary_key_columns(db_schema, missing_pk_tables)
            self.pk_columns_by_table.update(queried_pks)
            # Persist discovered PKs to avoid re-querying
            for schema in self.cdc_schemas:
                if schema.name in queried_pks:
                    self._update_schema_sync_type_config(
                        schema, updates={"primary_key_columns": queried_pks[schema.name]}
                    )

        self.log.info("pk_columns_loaded", tables=list(self.pk_columns_by_table.keys()))

        for schema in self.cdc_schemas:
            enabled = schema.enabled_columns
            # `None` = sync all; `[]` = retain PKs + incremental only. Match the
            # invariant used by build_select_clause / pipeline_sync / filter_dwh_columns.
            if isinstance(enabled, list):
                retained: set[str] = {str(c) for c in enabled}
                # PKs must stay even if the user dropped them from enabled_columns — merges break otherwise.
                for pk in self.pk_columns_by_table.get(schema.name, []):
                    retained.add(pk)
                inc = schema.incremental_field
                if isinstance(inc, str) and inc:
                    retained.add(inc)
                self.enabled_columns_by_table[schema.name] = retained

    def _project_event_columns(self, event: ChangeEvent) -> ChangeEvent:
        retained = self.enabled_columns_by_table.get(event.table_name)
        if retained is None:
            return event
        filtered = {name: value for name, value in event.columns.items() if name in retained}
        if filtered.keys() == event.columns.keys():
            return event
        return ChangeEvent(
            operation=event.operation,
            table_name=event.table_name,
            position_serialized=event.position_serialized,
            timestamp=event.timestamp,
            columns=filtered,
            column_types=event.column_types,
        )

    def _qualified_table_name(self, schema: ExternalDataSchema) -> str:
        default_schema = (self.source.job_inputs or {}).get("schema") if self.source else None
        return cdc_qualified_table_name(schema, default_schema)

    def _build_event_name_map(self) -> dict[str, str]:
        """Map each schema's source-qualified `schema.table` name to its stored `name`.

        WAL events are always qualified (`public.orders`) but `name` may be stored bare
        (`orders`), so an exact-equality match silently drops every change for a bare row.
        """
        mapping: dict[str, str] = {}
        for schema in self.cdc_schemas:
            mapping[self._qualified_table_name(schema)] = schema.name
            mapping.setdefault(schema.name, schema.name)  # also match a bare-emitted name
        return mapping

    # ------------------------------------------------------------------
    # WAL read loop with periodic micro-batch flushes
    # ------------------------------------------------------------------
    def _make_read_heartbeat(self) -> Callable[[], None]:
        """Throttled ``activity.heartbeat`` for ``read_changes``' per-row callback.

        The decoder yields nothing until a COMMIT, so a single large transaction would
        otherwise starve the 10m heartbeat timeout while it is being fetched. Throttled by
        wall-clock to avoid a heartbeat call on every WAL row.
        """
        last_heartbeat = 0.0

        def heartbeat() -> None:
            nonlocal last_heartbeat
            now = time.monotonic()
            if now - last_heartbeat >= CDC_READ_HEARTBEAT_INTERVAL_SECONDS:
                activity.heartbeat()
                last_heartbeat = now

        return heartbeat

    def _read_wal_loop(self) -> None:
        """Read WAL events with periodic micro-batch flushes, bounded per peek.

        Each pass peeks at most ``CDC_MAX_CHANGES_PER_READ`` changes so a large backlog can't
        push the activity past its 2h timeout. When a pass returns a full page, the slot is
        advanced past everything it committed and another pass runs, until the backlog drains,
        the soft deadline hits, or (defensively) the limit cap is reached.

        Streaming schemas get Kafka messages immediately after each S3 write. The slot is
        advanced after each successful flush so a long extraction never replays committed
        events on the next run.
        """
        assert self._run_started_at is not None
        event_name_to_schema_name = self._build_event_name_map()
        self.batcher = ChangeEventBatcher()
        on_row = self._make_read_heartbeat()

        limit = CDC_MAX_CHANGES_PER_READ
        while True:
            for event in self.reader.read_changes(upto_nchanges=limit, on_row=on_row):
                activity.heartbeat()

                # Resolve to the schema's stored `name` so downstream keying lines up. Log
                # unmatched drops: a silent drop here is how a name mismatch starves a table.
                canonical_name = event_name_to_schema_name.get(event.table_name)
                if canonical_name is None:
                    self.log.debug("cdc_event_dropped_unmatched_table", table=event.table_name)
                    continue
                if canonical_name != event.table_name:
                    event = dataclasses.replace(event, table_name=canonical_name)

                event = self._project_event_columns(event)
                self.batcher.add(event)

                # A change in position_serialized proves the previous transaction fully
                # yielded — all of its events are now buffered or flushed. Record its end LSN
                # as the high-water mark we may safely release the WAL up to.
                if event.position_serialized != self.current_txn_lsn:
                    self.last_complete_txn_end_lsn = self.current_txn_lsn
                    self.current_txn_lsn = event.position_serialized

                self.last_end_lsn = event.position_serialized
                self.event_count += 1

                if self.batcher.should_flush:
                    tables = self.batcher.flush()
                    self.all_table_names.update(tables.keys())
                    self._process_flush(tables, is_final=False)
                    metrics.get_micro_batches_flushed_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)
                    # Advance only to the end of the last FULLY-yielded transaction, never to
                    # last_end_lsn: a micro-flush can fire mid-transaction (the batcher
                    # threshold is checked per event), and every event of the in-flight
                    # transaction shares its commit end LSN. Confirming that LSN while the
                    # transaction's tail is still un-yielded in the generator would release
                    # the WAL past un-flushed events — a crash before the next flush then
                    # loses them permanently. Consequences of this conservative bound:
                    #   (a) a single giant transaction gets no micro-advance until it
                    #       completes (a retry re-decodes it — safe, slow);
                    #   (b) on crash-replay the already-flushed prefix of the in-flight
                    #       transaction is re-delivered — incremental_merge dedups by PK,
                    #       scd2_append may create duplicate history rows. Accepted vs. loss.
                    if (
                        self.last_complete_txn_end_lsn is not None
                        and self.last_complete_txn_end_lsn != self.last_confirmed_lsn
                    ):
                        self._confirm_position(self.last_complete_txn_end_lsn)
                        self.last_confirmed_lsn = self.last_complete_txn_end_lsn
                    self.log.info(
                        "cdc_micro_batch_flushed",
                        events_so_far=self.event_count,
                        trackers=len(self.write_trackers),
                    )

            # Capture remaining table names before deciding on the next pass / final flush.
            self.all_table_names.update(self.batcher.table_names)

            rows_consumed = self.reader.last_rows_consumed
            # Drained: the peek returned less than a full page, so the backlog is exhausted.
            # Leave any buffered tail for run()'s _final_flush (is_final=True) + advance.
            if rows_consumed < limit:
                return

            if (time.monotonic() - self._run_started_at) >= CDC_READ_SOFT_DEADLINE_SECONDS:
                self.log.warning(
                    "cdc_read_soft_deadline_reached",
                    events_so_far=self.event_count,
                    rows_consumed=rows_consumed,
                )
                return

            # Full page: drain the buffered (committed) events and advance the slot past every
            # transaction this pass committed so the next peek resumes cleanly.
            #
            # A full page that advanced nothing is a defensive guard, not a live path:
            # pg_logical_slot_peek_binary_changes only returns fully-committed transactions, so a
            # page that returns rows always commits something and advances. Were that ever to not
            # hold, grow the window so an oversized single transaction can complete in one peek (or
            # trip the decoder's MAX_TX_BUFFER_EVENTS guard) instead of re-peeking the same page.
            if not self._drain_and_advance_page():
                limit = min(limit * 2, CDC_MAX_CHANGES_LIMIT_CAP)

    def _drain_and_advance_page(self) -> bool:
        """Between peeks: flush buffered events and advance the slot past every committed
        transaction. Returns whether the slot advanced.

        Safe to advance to the decoder's last commit end LSN here (not only to
        last_complete_txn_end_lsn as the mid-loop micro-flush does): the peek has stopped at a
        transaction boundary, so every event yielded this pass belongs to a committed
        transaction and is now flushed. Unmatched-table commits carry the slot forward too —
        their WAL is intentionally dropped. Re-reading instead would re-add already-flushed
        events and duplicate SCD2 history rows.
        """
        assert self.batcher is not None
        if self.batcher.event_count > 0:
            tables = self.batcher.flush()
            self.all_table_names.update(tables.keys())
            self._process_flush(tables, is_final=False)
            metrics.get_micro_batches_flushed_metric(self.inputs.team_id, str(self.inputs.source_id)).add(1)

        commit_lsn = self.reader.last_commit_end_lsn
        if commit_lsn is not None and commit_lsn != self.last_confirmed_lsn:
            self._confirm_position(commit_lsn)
            self.last_confirmed_lsn = commit_lsn
            self.last_end_lsn = commit_lsn
            activity.heartbeat()
            return True
        return False

    # ------------------------------------------------------------------
    # Post-WAL handling
    # ------------------------------------------------------------------
    def _handle_pk_changes_post_wal(self) -> None:
        """Detect PK column changes that surfaced during decoding."""
        for table_name in self.all_table_names:
            decoder_pks = self.reader.get_decoder_key_columns(table_name)
            stored_pks = self.pk_columns_by_table.get(table_name, [])
            if decoder_pks and decoder_pks != stored_pks:
                pk_schema = self.schema_by_name.get(table_name)
                pk_log = self._schema_log(pk_schema) if pk_schema is not None else self.log
                pk_log.warning("pk_columns_changed", table=table_name, old=stored_pks, new=decoder_pks)
                self.pk_columns_by_table[table_name] = decoder_pks
                if pk_schema is not None:
                    self._update_schema_sync_type_config(pk_schema, updates={"primary_key_columns": decoder_pks})

    def _handle_truncates(self) -> list[str]:
        """Process any truncated tables observed during decoding.

        Returns the list of truncated table names so the no-changes path can
        decide whether to advance the slot.
        """
        truncated_tables = list(self.reader.truncated_tables)
        self.reader.clear_truncated_tables()
        for table_name in truncated_tables:
            trunc_schema = self.schema_by_name.get(table_name)
            if trunc_schema is None:
                continue
            self._schema_log(trunc_schema).warning(
                "truncate_detected", table=table_name, schema_id=str(trunc_schema.id)
            )
            self._reset_schema_to_snapshot(trunc_schema)
            self._unpause_schema_schedule(trunc_schema)
        return truncated_tables

    def _reset_schema_to_snapshot(self, schema: ExternalDataSchema, *, clear_deferred_runs: bool = False) -> None:
        """Put a schema back into snapshot mode so its own schedule re-syncs it from scratch."""
        removes = ["cdc_last_log_position"]
        if clear_deferred_runs:
            removes.append("cdc_deferred_runs")
        # reset_pipeline forces the batch import to wipe the table first (handle_reset_or_full_refresh),
        # preventing pre-truncate rows from surviving a TRUNCATE or lost-slot re-snapshot.
        self._update_schema_sync_type_config(
            schema,
            updates={"cdc_mode": "snapshot", "reset_pipeline": True},
            removes=removes,
            extra_model_fields={"initial_sync_complete": False},
        )
        if clear_deferred_runs:
            self._emit_deferred_runs_depth()

    def _unpause_schema_schedule(self, schema: ExternalDataSchema) -> None:
        schema_log = self._schema_log(schema)
        try:
            from products.data_warehouse.backend.facade.api import unpause_external_data_schedule

            unpause_external_data_schedule(str(schema.id))
            schema_log.info("unpaused_schema_schedule_for_resnapshot", schema_id=str(schema.id))
        except Exception:
            schema_log.warning("failed_to_unpause_schema_schedule", schema_id=str(schema.id), exc_info=True)

    def _handle_no_changes(self, truncated_tables: list[str]) -> None:
        """Early-return path: no DML events were read."""
        if truncated_tables:
            truncate_end_lsn = self.reader.last_commit_end_lsn
            if truncate_end_lsn is not None:
                self._confirm_position(truncate_end_lsn)
                self.log.info("slot_advanced_past_truncate", position=truncate_end_lsn)

        now = dt.datetime.now(tz=dt.UTC)
        for schema in self.cdc_schemas:
            schema.status = ExternalDataSchema.Status.COMPLETED
            schema.latest_error = None
            schema.last_synced_at = now
            schema.save(update_fields=["status", "latest_error", "last_synced_at", "updated_at"])
            self._record_run_heartbeat(schema, now)
            # Per-schema breadcrumb so the Syncs UI shows _why_ the latest run produced no rows.
            self._schema_log(schema).info(
                "cdc_extract_no_changes",
                truncated_tables=truncated_tables,
            )
        self.log.info("no_wal_changes")
        self._emit_run_duration("no_changes")

    # ------------------------------------------------------------------
    # Flush + finalization
    # ------------------------------------------------------------------
    def _flush_pending_deferred_runs(self) -> None:
        """Flush deferred runs for schemas that transitioned to streaming."""
        assert self.source is not None
        for schema in self.cdc_schemas:
            if schema.cdc_mode == "streaming" and schema.sync_type_config.get("cdc_deferred_runs"):
                self._flush_deferred_runs(schema)

    def _final_flush(self) -> set[str]:
        """Flush remaining buffered events with is_final_batch=True."""
        assert self.batcher is not None
        if self.batcher.event_count > 0:
            tables = self.batcher.flush()
            return self._process_flush(tables, is_final=True)
        return set()

    def _finalize_trackers(self, final_flushed: set[str]) -> None:
        """Finalize trackers after the read loop has drained.

        - Streaming trackers that had no data in the final flush need an
          empty finalization batch so the consumer triggers post-load ops.
        - Snapshot trackers: batch results were already persisted to
          sync_type_config by _store_deferred_batch; write schema file
          and update the deferred entry with the final schema_path.
        """
        for resource_name, tracker in self.write_trackers.items():
            schema = self.schema_by_name[tracker.table_name]

            if schema.cdc_mode == "streaming":
                if resource_name not in final_flushed:
                    # Write a zero-row parquet so the consumer has a valid s3_path to
                    # read.  It processes 0 rows (DeltaLake no-op) but still runs
                    # post-load ops and marks the job completed.
                    empty = pa.table({"_empty": pa.array([], type=pa.int8())})
                    finalize_result = tracker.s3_writer.write_batch(empty, batch_index=tracker.batch_index)
                    tracker.batch_index += 1
                    self._send_batch_notification(tracker, finalize_result, is_final_batch=True)

                tracker.job.rows_synced = tracker.total_rows
                tracker.job.save(update_fields=["rows_synced", "updated_at"])

            elif schema.cdc_mode == "snapshot":
                # Write schema file and update the deferred entry with final metadata.
                schema_path = tracker.s3_writer.write_schema()
                if schema_path is not None:
                    self._persist_deferred_finalization(schema, tracker, schema_path)

                tracker.job.rows_synced = tracker.total_rows
                tracker.job.status = ExternalDataJob.Status.COMPLETED
                tracker.job.finished_at = dt.datetime.now(tz=dt.UTC)
                tracker.job.save(update_fields=["rows_synced", "status", "finished_at", "updated_at"])

    def _advance_slot_after_run(self) -> None:
        """Advance the slot to the last LSN if the final flush moved past the last incremental advance.

        Intermediate micro-batches already advanced the slot incrementally inside the
        read loop, so this only fires if the final flush contained new events beyond
        the last incremental advance.
        """
        if self.last_end_lsn is not None and self.last_end_lsn != self.last_confirmed_lsn:
            self._confirm_position(self.last_end_lsn)
            self.log.info("slot_advanced", position=self.last_end_lsn)

    def _update_log_positions(self) -> None:
        """Update per-schema cdc_last_log_position (skip schemas reset to snapshot mode)."""
        if self.last_end_lsn is None:
            return
        for schema in self.cdc_schemas:
            if schema.sync_type_config.get("cdc_mode") == "snapshot":
                continue
            self._update_schema_sync_type_config(schema, updates={"cdc_last_log_position": self.last_end_lsn})

    # ------------------------------------------------------------------
    # Failure / success finalization
    # ------------------------------------------------------------------
    def _fail_created_jobs(self, error: str) -> None:
        for job in self.created_jobs:
            if job.status == ExternalDataJob.Status.RUNNING:
                job.status = ExternalDataJob.Status.FAILED
                job.latest_error = error
                job.finished_at = dt.datetime.now(tz=dt.UTC)
                job.save(update_fields=["status", "latest_error", "finished_at", "updated_at"])

    def _recover_from_slot_invalidation(self, exc: Exception) -> None:
        """The slot can't be resumed (invalidated or dropped on the source DB): recreate it
        and reset every CDC schema to snapshot mode so it re-syncs from current table state.

        WAL between the slot's last confirmed position and the new slot's consistent point is
        gone — the re-snapshot covers current rows, but intermediate changes in that gap
        (including their _cdc history rows) cannot be recovered.
        """
        assert self.source is not None
        assert self.adapter is not None
        self.log.warning("cdc_slot_unrecoverable_recreating", error=str(exc))

        self._fail_created_jobs(SLOT_INVALIDATION_RECOVERY_MESSAGE)

        # Reset schemas before touching the slot (schedules stay paused): if recreation
        # fails below, the next run hits the invalidation again and recovery reruns
        # idempotently — no schema keeps streaming across the gap unnoticed. Deferred
        # runs are dropped: they reference WAL from the dead slot, the re-snapshot
        # supersedes them, and flushing them later would merge stale rows over fresh ones.
        for schema in self.cdc_schemas:
            self._reset_schema_to_snapshot(schema, clear_deferred_runs=True)
            schema.status = ExternalDataSchema.Status.FAILED
            schema.latest_error = SLOT_INVALIDATION_RECOVERY_MESSAGE
            schema.save(update_fields=["status", "latest_error", "updated_at"])
            self._schema_log(schema).warning("cdc_schema_reset_for_slot_recovery", schema_id=str(schema.id))

        resource_fields = self.adapter.recreate_slot(
            self.source, tables=[self._qualified_table_name(s) for s in self.cdc_schemas]
        )

        self.source.job_inputs = {**(self.source.job_inputs or {}), **resource_fields}
        self.source.save(update_fields=["job_inputs", "updated_at"])

        # Unpause only after the new slot exists, so no snapshot can run before change
        # capture has a consistent point to resume from.
        for schema in self.cdc_schemas:
            self._unpause_schema_schedule(schema)

        self.log.info("cdc_slot_recovery_complete", schemas_reset=len(self.cdc_schemas))

    def _fail(self, exc: Exception) -> typing.NoReturn:
        """Persist a friendly failure, emit analytics, and re-raise.

        Non-retryable classifications raise ``NonRetryableException`` so the workflow's retry
        policy stops re-running a deterministic failure; retryable ones re-raise as-is to let
        Temporal retry.
        """
        info = self._handle_failure(exc)
        if not info.retryable:
            self._capture_non_retryable(info)
            raise NonRetryableException(info.friendly_message) from exc
        raise exc

    def _handle_failure(self, exc: Exception) -> CDCErrorInfo:
        """Classify the failure, store the friendly message on the jobs/schemas, return the info."""
        self.log.exception("cdc_extract_failed")
        info = classify_cdc_error(exc, self.adapter)
        friendly = info.friendly_message[:MAX_FRIENDLY_MESSAGE_LENGTH]
        self._fail_created_jobs(friendly)
        # A missing slot/publication won't recover on retry: mark the source broken — that persists
        # the per-schema FAILED state + the cdc_broken marker the UI/health check read and pauses the
        # schedule, so it stops firing hourly against a resource that is gone (the same zombie the lag
        # safety net produces). Any other failure just fails this run's schemas.
        marked_broken = info.category in (CDCErrorCategory.SLOT_MISSING, CDCErrorCategory.PUBLICATION_MISSING)
        if marked_broken:
            assert self.source is not None
            mark_cdc_broken(self.source, info.category.value, friendly)
        for schema in self.cdc_schemas:
            if not marked_broken:
                schema.status = ExternalDataSchema.Status.FAILED
                schema.latest_error = friendly
                schema.save(update_fields=["status", "latest_error", "updated_at"])
            # User-facing column gets the friendly copy; the raw error still routes to structured
            # logs / the Syncs log viewer for debugging.
            self._schema_log(schema).error(
                "cdc_extract_schema_failed", error=str(exc), category=info.category, retryable=info.retryable
            )
        # A failure before the first micro-flush creates no ExternalDataJob, so the Syncs tab stays
        # empty while the schema reads FAILED. Backfill a terminal FAILED row per schema so the run
        # is visible — but only once retries are exhausted or the error is non-retryable, otherwise
        # every transient retry would leave a stray failed row.
        if not self.created_jobs and (activity.info().attempt >= CDC_MAX_EXTRACTION_ATTEMPTS or not info.retryable):
            try:
                self._create_failure_visibility_jobs(friendly)
            except Exception:
                self.log.warning("cdc_failure_visibility_jobs_failed", exc_info=True)
        self._emit_run_duration("failed")
        return info

    def _capture_non_retryable(self, info: CDCErrorInfo) -> None:
        # Best-effort: analytics must never mask the NonRetryableException the caller is about to raise.
        try:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="cdc extraction non-retryable error",
                properties={
                    "team_id": self.inputs.team_id,
                    "source_id": str(self.inputs.source_id),
                    "category": str(info.category),
                },
            )
        except Exception:
            self.log.warning("cdc_non_retryable_capture_failed", exc_info=True)

    def _create_failure_visibility_jobs(self, friendly_error: str) -> None:
        """Create one terminal FAILED ExternalDataJob per CDC schema for a run that produced none.

        Mirrors the running-job creation in _get_or_create_tracker (workflow ids, V3, snapshot) so
        the Syncs tab renders these the same way as a job that failed after it started writing.
        """
        now = dt.datetime.now(tz=dt.UTC)
        activity_info = activity.info()
        for schema in self.cdc_schemas:
            ExternalDataJob.objects.create(
                team_id=self.inputs.team_id,
                pipeline_id=self.inputs.source_id,
                schema=schema,
                status=ExternalDataJob.Status.FAILED,
                rows_synced=0,
                latest_error=friendly_error,
                workflow_id=activity_info.workflow_id,
                workflow_run_id=activity_info.workflow_run_id,
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
                finished_at=now,
                schema_snapshot=_build_schema_snapshot(schema),
            )

    def _record_run_heartbeat(self, schema: ExternalDataSchema, run_at: dt.datetime) -> None:
        """Persist a per-schema last-run heartbeat (cdc_last_run_at / cdc_last_run_event_count) so a
        quiet zero-event run still proves extraction is alive. Nothing reads these keys yet — an
        upcoming CDC health check and the status endpoint will — so this is a forward-looking
        breadcrumb, not an ExternalDataJob row per idle run.
        """
        self._update_schema_sync_type_config(
            schema,
            updates={"cdc_last_run_at": run_at.isoformat(), "cdc_last_run_event_count": self.event_count},
        )

    def _finalize_success(self) -> None:
        now = dt.datetime.now(tz=dt.UTC)
        synced_tables = {tracker.table_name for tracker in self.write_trackers.values()}
        for schema in self.cdc_schemas:
            schema.status = ExternalDataSchema.Status.COMPLETED
            schema.latest_error = None
            schema.last_synced_at = now
            schema.save(update_fields=["status", "latest_error", "last_synced_at", "updated_at"])
            self._record_run_heartbeat(schema, now)
            # Breadcrumb for idle tables; _handle_no_changes only covers the whole-source-quiet case.
            if schema.name not in synced_tables:
                self._schema_log(schema).info("cdc_extract_no_changes")
        self._emit_run_duration("completed")


@activity.defn
def cdc_extract_activity(inputs: CDCExtractInput) -> None:
    """Core CDC extraction activity. Thin wrapper around CDCExtractActivity."""
    CDCExtractActivity(inputs).run()


@activity.defn
def validate_cdc_prerequisites_activity(inputs: ValidateCDCPrerequisitesInput) -> list[str]:
    """Validate CDC prerequisites for a source. Returns list of error messages."""
    close_old_connections()

    source = ExternalDataSource.objects.get(pk=inputs.source_id)
    adapter = get_cdc_adapter(source)

    return adapter.validate_prerequisites(
        source=source,
        management_mode=inputs.management_mode,  # type: ignore[arg-type]
        tables=inputs.tables,
        schema=inputs.schema,
        slot_name=inputs.slot_name,
        publication_name=inputs.publication_name,
    )


# ---------------------------------------------------------------------------
# Orphan slot sweeper
# ---------------------------------------------------------------------------


@activity.defn
def cleanup_orphan_slots_activity() -> None:
    """Safety-net sweeper: clean up orphaned CDC slots and monitor WAL lag.

    1. For deleted/inactive PostHog-managed sources → drop slot + publication
    2. For active sources → check WAL lag:
       - Warning threshold: log warning, update source status
       - Critical threshold (PostHog-managed, safety net on): drop slot, mark error
       - Self-managed: never drop, only warn
    """
    close_old_connections()

    log = logger.bind()
    log.info("cleanup_orphan_slots_started")
    sweep_started_mono = time.monotonic()
    sweep_started = dt.datetime.now(tz=dt.UTC)

    # The CDC fields live in `job_inputs`, an EncryptedJSONField: every leaf value is
    # Fernet-encrypted at rest, so `job_inputs__cdc_enabled=True` (and the slot/publication
    # filters) can never match. We must scope by the unencrypted `source_type` column and
    # decode each source's CDC config in Python. Deleted sources are included on purpose —
    # cleaning up their orphaned slots is the whole point of this sweep.
    sources = ExternalDataSource.objects.filter(source_type__in=cdc_supported_source_types()).iterator(chunk_size=100)

    sources_checked = 0
    sources_errored = 0
    slots_dropped = 0
    # A single source's management connection (10s connect_timeout × several ops) can stall the
    # loop, so heartbeat from a background thread rather than once per iteration — otherwise a
    # stalled source would starve heartbeats and Temporal would kill the whole sweep.
    with HeartbeaterSync(logger=log):
        for source in sources:
            try:
                adapter = get_cdc_adapter(source)
            except ValueError:
                continue

            try:
                cdc_config = adapter.parse_cdc_config(source)
            except Exception:
                log.exception("failed_to_parse_cdc_config", source_id=str(source.id))
                metrics.get_sweeper_source_errors_metric().add(1)
                sources_errored += 1
                continue

            # Restore the original filter semantics on decrypted values: skip sources that
            # don't have CDC enabled with both a slot and publication name to clean up.
            if not (cdc_config.enabled and cdc_config.slot_name and cdc_config.publication_name):
                continue

            sources_checked += 1

            source_log = log.bind(
                source_id=str(source.id),
                team_id=source.team_id,
                slot_name=cdc_config.slot_name,
                management_mode=cdc_config.management_mode,
            )

            # 1. Deleted sources — drop the Temporal schedule (always; PostHog-side)
            #    and PostHog-managed slot/publication (only when we own them).
            if source.deleted:
                try:
                    from products.data_warehouse.backend.facade.api import delete_cdc_extraction_schedule

                    delete_cdc_extraction_schedule(str(source.id))
                except Exception:
                    source_log.exception("failed_to_delete_cdc_extraction_schedule")
                    metrics.get_sweeper_source_errors_metric().add(1)

                if cdc_config.management_mode == "posthog":
                    source_log.info("cleaning_up_deleted_source_slot")
                    try:
                        with adapter.management_connection(source, connect_timeout=10) as conn:
                            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)
                        slots_dropped += 1
                    except Exception:
                        source_log.exception("failed_to_cleanup_deleted_source_slot")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1
                continue

            # 2. Active sources — check WAL lag
            source_started = dt.datetime.now(tz=dt.UTC)
            try:
                with adapter.management_connection(source, connect_timeout=10) as conn:
                    lag_bytes = adapter.get_lag_bytes(conn, cdc_config.slot_name)
                    retention_cap_mb = adapter.get_retention_cap_mb(conn)
            except Exception:
                source_log.exception("failed_to_check_slot_lag")
                metrics.get_sweeper_source_errors_metric().add(1)
                sources_errored += 1
                continue

            if lag_bytes is None:
                source_log.warning("slot_not_found_or_no_flush_lsn")
                continue

            metrics.get_wal_lag_metric(source.team_id, str(source.id)).set(lag_bytes)
            lag_mb = lag_bytes / (1024 * 1024)

            critical_threshold_mb = cdc_config.lag_critical_threshold_mb
            if retention_cap_mb is not None:
                critical_threshold_mb = min(critical_threshold_mb, int(retention_cap_mb * RETENTION_CAP_SAFETY_FACTOR))

            if lag_mb >= critical_threshold_mb:
                source_log.error(
                    "slot_lag_critical",
                    lag_mb=round(lag_mb, 1),
                    threshold_mb=critical_threshold_mb,
                    retention_cap_mb=retention_cap_mb,
                )

                if cdc_config.management_mode == "posthog" and cdc_config.auto_drop_slot:
                    source_log.warning("auto_dropping_slot_critical_lag")
                    try:
                        with adapter.management_connection(source, connect_timeout=10) as conn:
                            adapter.drop_resources(conn, cdc_config.slot_name, cdc_config.publication_name)

                        slots_dropped += 1
                        metrics.get_auto_drop_metric(source.team_id, str(source.id)).add(1)
                        # The slot is gone — move the source to an explicit broken state and pause the
                        # schedule so it stops retrying against a slot that no longer exists.
                        mark_cdc_broken(
                            source,
                            "auto_dropped_critical_lag",
                            f"Change data capture was automatically stopped because replication lag "
                            f"exceeded {critical_threshold_mb} MB and the safety net dropped the "
                            f"replication slot. Use Repair CDC to recreate it and re-sync.",
                            lag_mb=round(lag_mb, 1),
                        )
                    except Exception:
                        source_log.exception("failed_to_auto_drop_slot")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1
                elif cdc_config.management_mode == "self_managed":
                    # Customer owns the slot: surface the broken state but keep the schedule running
                    # and never drop — the lag may recover once they reduce load on the source.
                    try:
                        mark_cdc_broken(
                            source,
                            "critical_lag_self_managed",
                            f"Change data capture replication lag exceeded {critical_threshold_mb} MB. "
                            f"This slot is self-managed, so PostHog did not drop it — reduce load or WAL "
                            f"retention on the source database, or it may invalidate the slot and "
                            f"require a full re-sync.",
                            pause=False,
                            lag_mb=round(lag_mb, 1),
                        )
                    except Exception:
                        source_log.exception("failed_to_mark_self_managed_broken")
                        metrics.get_sweeper_source_errors_metric().add(1)
                        sources_errored += 1

            elif lag_mb >= cdc_config.lag_warning_threshold_mb:
                source_log.warning(
                    "slot_lag_warning",
                    lag_mb=round(lag_mb, 1),
                    threshold_mb=cdc_config.lag_warning_threshold_mb,
                )

            source_log.info(
                "slot_lag_checked",
                lag_mb=round(lag_mb, 1),
                duration_ms=round((dt.datetime.now(tz=dt.UTC) - source_started).total_seconds() * 1000),
            )

    metrics.get_sweeper_sources_checked_metric().add(sources_checked)
    metrics.get_sweeper_duration_metric().record(time.monotonic() - sweep_started_mono)
    log.info(
        "cleanup_orphan_slots_completed",
        sources_checked=sources_checked,
        sources_errored=sources_errored,
        slots_dropped=slots_dropped,
        duration_s=round((dt.datetime.now(tz=dt.UTC) - sweep_started).total_seconds(), 1),
    )
