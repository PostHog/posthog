import time
import asyncio
import datetime
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator
from typing import TYPE_CHECKING, Any, Generic

import pyarrow as pa
import posthoganalytics
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.activity_context import current_workflow_id, current_workflow_run_id
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError
from posthog.utils import get_machine_id

from products.warehouse_sources.backend.models import DataWarehouseTable
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    process_incremental_value,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import SCD2_APPEND_MODE
from products.warehouse_sources.backend.temporal.data_imports.import_attempt import (
    current_import_attempt,
    current_import_attempt_cause,
)
from products.warehouse_sources.backend.temporal.data_imports.metrics import get_shutdown_handoff_delay_metric
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    cleanup_memory,
    commit_source_cursor,
    finalize_desc_sort_incremental_value,
    handle_corrupted_delta_log,
    handle_reset_or_full_refresh,
    is_young_first_attempt,
    persist_primary_keys,
    reset_rows_synced_if_needed,
    resolve_primary_keys,
    setup_row_tracking_with_billing_check,
    should_check_shutdown,
    update_incremental_field_values,
    update_row_tracking_after_batch,
    validate_incremental_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.preemption import (
    PreemptionConfig,
    PreemptionDecision,
    ShutdownStopwatch,
    SourcePreemptedError,
    SourcePreemptor,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.safe_point import (
    PipelineSafePointHandler,
    source_items_are_framework_output,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    _append_debug_column_to_pyarrows_table,
    _handle_null_columns_with_definitions,
    evolve_pyarrow_schema,
    merge_observed_columns_into_schema_metadata,
    normalize_column_name,
    normalize_table_column_names,
    observe_and_project_table,
    reconcile_batch_to_accumulated_schema,
    source_uses_delta_write_column_selection,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.async_iterate import async_iterate
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.sinks import (
    PipelineSinks,
    build_pipeline_sinks,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.table_stats import record_source_item_stats
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.handoff_checkpoint import (
    IncrementalBatchRangeReader,
    IncrementalHandoffCheckpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.metrics import (
    get_batches_produced_metric,
    get_pipeline_run_duration_metric,
    get_rows_extracted_metric,
    get_run_attempt_metric,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    PostgresProducer,
    SyncTypeLiteral,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import (
    BatchWriteResult,
    S3BatchWriter,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer import ParquetCompression
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import (
    ResumableSourceManager,
    resolve_resume_manager,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    ResumableData,
    SourceResponse,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
        ImportJobModels,
    )

PARQUET_COMPRESSION: ParquetCompression = "zstd"

# How long a preemption waits for a write of the source's resume state that is in progress.
SOURCE_FENCE_TIMEOUT_SECONDS = 5.0


def should_coalesce_tables(*, resume_manager: ResumableSourceManager[Any] | None, is_webhook: bool) -> bool:
    """Whether the batcher may merge small Arrow tables before staging a batch.

    Coalescing keeps a driver's fetch size (e.g. a SQL cursor's 10k-row Arrow tables) from becoming
    the queue's batch granularity, but it delays when a yielded table is persisted. So it has to stay
    off for sources that treat a yield as durable: the webhook path deletes its staged S3 files right
    after yielding, and a resume cursor commit assumes the write that preceded it drained every table
    yielded so far.

    Pass the *resolved* manager, never the raw one. A resumable source class whose current run cannot
    resume commits no cursor, so it is free to coalesce — and reading the raw manager here would
    switch coalescing off for every run of every such class, most of which never checkpoint.
    """
    return resume_manager is None and not is_webhook


class PipelineV3(Generic[ResumableData]):
    _resource: SourceResponse
    _resource_name: str
    _job: ExternalDataJob
    _source: ExternalDataSource
    _schema: ExternalDataSchema
    _table: DataWarehouseTable | None
    _logger: FilteringBoundLogger
    _is_incremental: bool
    _reset_pipeline: bool
    _delta_table_ref: DeltaTableRef
    _resumable_source_manager: ResumableSourceManager[ResumableData] | None
    _source_cursor_manager: SourceCursorManager[Any] | None
    _internal_schema: HogQLSchema
    _sinks: PipelineSinks
    _batcher: Batcher
    _load_id: int
    _s3_batch_writer: S3BatchWriter
    _pg_producer: PostgresProducer
    _accumulated_pa_schema: pa.Schema | None
    _batch_results: list[BatchWriteResult]
    # Set only for a run that can continue from its last queued batch after an interruption.
    _handoff_checkpoint: IncrementalHandoffCheckpoint | None = None
    _batch_range_reader: IncrementalBatchRangeReader
    _staged_handoff_resume_value: Any = None
    _staged_handoff_resume_owner: str | None = None
    # True once this attempt has queued a batch of its own, rather than only inheriting the
    # resume value an earlier attempt recorded. Decides who owns the queue rows the value describes.
    _queued_own_batch: bool = False
    # True when this attempt reads the source after a value an earlier attempt of the run recorded.
    _continues_incremental_handoff: bool = False
    # The manager the source holds, also when this run cannot resume from it.
    _source_resume_manager: ResumableSourceManager[ResumableData] | None = None
    # None when the pipeline waits for the source for as long as the source takes.
    _preemption: PreemptionConfig | None = None
    _shutdown_stopwatch: ShutdownStopwatch | None = None
    _resumed_incremental_run_uuid: str | None = None
    _sent_resumed_run_finalization: bool = False

    def __init__(
        self,
        source_response: SourceResponse,
        logger: FilteringBoundLogger,
        job_id: str,
        reset_pipeline: bool,
        shutdown_monitor: ShutdownMonitor,
        resumable_source_manager: ResumableSourceManager[ResumableData] | None,
        *,
        models: "ImportJobModels",
        source_cursor_manager: SourceCursorManager[Any] | None = None,
        incremental_checkpoints_allowed: bool = False,
        resumed_incremental_run_uuid: str | None = None,
        resumed_incremental_value: Any = None,
        preemption: PreemptionConfig | None = None,
    ) -> None:
        self._resource = source_response
        self._source_cursor_manager = source_cursor_manager
        self._resource_name = source_response.name

        # Persisted PK (user override or earlier detection) > live-detected > `id` fallback. Keeps
        # the merge key stable across runs when live detection (e.g. Snowflake SHOW PRIMARY KEYS)
        # intermittently returns nothing.
        self._resource.primary_keys = resolve_primary_keys(models.schema, self._resource)

        self._job = models.job
        self._reset_pipeline = reset_pipeline
        self._logger = logger
        self._load_id = time.time_ns()

        self._schema = models.schema
        self._source = models.source
        self._table = models.table
        # xmin reads deltas and upserts on the primary key, so it writes incrementally too — never
        # as a full_refresh overwrite, which would wipe earlier data on the second (delta-only) sync.
        # Same for a change stream, which only ever carries the rows that changed.
        self._is_incremental = (
            models.schema.is_incremental
            or models.schema.is_webhook
            or models.schema.is_xmin
            or source_response.cdc_write_mode is not None
        )

        self._delta_table_ref = DeltaTableRef(
            self._resource_name, self._job, self._logger, expect_missing=models.table is None
        )

        attempt = current_import_attempt()
        self._attempt = attempt
        self._run_uuid = f"{self._job.workflow_run_id}-a{attempt}" if self._job.workflow_run_id else None
        self._s3_batch_writer = self._build_s3_writer(self._run_uuid)

        sync_type: SyncTypeLiteral = "full_refresh"
        if source_response.cdc_write_mode is not None:
            sync_type = "cdc"
        elif self._schema.is_incremental or self._schema.is_webhook or self._schema.is_xmin:
            sync_type = "incremental"
        elif self._schema.is_append:
            sync_type = "append"

        # Operator-pinned overrides (admin repartition action) win over the auto-detected
        # persisted value and the source-computed value. See setup_partitioning in the v2
        # pipeline for the same precedence and rationale.
        partition_count = (
            self._schema.partition_count_override or self._schema.partition_count or self._resource.partition_count
        )
        partition_size = (
            self._schema.partition_size_override or self._schema.partition_size or self._resource.partition_size
        )
        partition_keys = (
            self._schema.partitioning_keys_override
            or self._schema.partitioning_keys
            or self._resource.partition_keys
            or self._resource.primary_keys
        )
        partition_format = self._schema.partition_format or self._resource.partition_format
        partition_mode = (
            self._schema.partition_mode_override or self._schema.partition_mode or self._resource.partition_mode
        )

        # Determine if this is the first-ever sync (no DWH table exists yet)
        is_first_ever_sync = self._schema.table is None

        # SQL sources project enabled_columns in their SELECT and own schema_metadata via
        # introspection; managed-schema sources don't allow selection. Everything else gets the
        # write-side drop plus observed-columns capture so the column picker has a catalog.
        self._uses_delta_write_column_selection = source_uses_delta_write_column_selection(models.source.source_type)
        self._observed_columns: dict[str, dict[str, Any]] = {}

        self._source_resume_manager = resumable_source_manager
        self._resumable_source_manager = resolve_resume_manager(resumable_source_manager, self._resource)
        self._preemption = preemption
        # The earlier attempts of this run queued every row up to the value this attempt reads after,
        # and this attempt does not extract those rows again. The queue must therefore treat it as a
        # resume: a fresh run replaces the queue rows of earlier attempts and overwrites on batch 0.
        self._continues_incremental_handoff = resumed_incremental_value is not None
        self._resumed_incremental_run_uuid = resumed_incremental_run_uuid
        self._sent_resumed_run_finalization = False
        is_resume = self._continues_incremental_handoff or (
            self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        )
        if incremental_checkpoints_allowed and self._tracks_handoff_checkpoint(source_response, reset_pipeline):
            self._handoff_checkpoint = IncrementalHandoffCheckpoint(resumed_incremental_value)
            self._batch_range_reader = IncrementalBatchRangeReader(self._schema)

        # Resolved in `_get_models`, not here: the pipeline is built inside an async activity,
        # so the query that tells the warehouse from an external destination cannot run here.
        self._external_destination_ids: list[str] = list(models.external_destination_ids)

        self._producer_kwargs: dict[str, Any] = {
            "sync_type": sync_type,
            "is_resume": is_resume,
            "partition_count": partition_count,
            "partition_size": partition_size,
            "partition_keys": partition_keys,
            "partition_format": partition_format,
            "partition_mode": partition_mode,
            "is_first_ever_sync": is_first_ever_sync,
        }
        self._pg_producer = self._build_producer(
            self._s3_batch_writer, resource_name=self._resource_name, cdc_write_mode=self._resource.cdc_write_mode
        )

        # A source can shrink the batcher chunk (e.g. document sources with large rows) so the
        # source->Arrow conversion doesn't materialise an oversized table; None falls back to defaults.
        self._batcher = Batcher(
            self._logger,
            chunk_size=source_response.chunk_size,
            chunk_size_bytes=source_response.chunk_size_bytes,
            source_type=self._source.source_type if self._source else None,
            team_id=self._job.team_id,
            schema_name=self._schema.name,
            coalesce_tables=should_coalesce_tables(
                resume_manager=self._resumable_source_manager, is_webhook=self._schema.is_webhook
            ),
            primary_keys=self._resource.primary_keys,
        )
        self._internal_schema = HogQLSchema()
        self._sinks = build_pipeline_sinks(
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            job_id=job_id,
            logger=self._logger,
            is_incremental=self._is_incremental,
        )
        self._accumulated_pa_schema = None
        self._batch_results = []
        self._shutdown_monitor = shutdown_monitor
        self._shutdown_stopwatch = ShutdownStopwatch(shutdown_monitor)
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            models.schema.incremental_field_earliest_value, models.schema.incremental_field_type
        )

    def _tracks_handoff_checkpoint(self, source_response: SourceResponse, reset_pipeline: bool) -> bool:
        """Whether a later attempt of this run can continue from the batches this attempt queues.

        The source must promise ascending order, and nothing else may own the restart point: a
        source that resumes from its own cursor reads that cursor, and a reset reloads the table.
        A run that writes several tables keeps one queue per table, which one value cannot cover.
        """
        return (
            self._schema.is_incremental
            and bool(self._schema.incremental_field)
            and source_response.sort_mode == "asc"
            and not reset_pipeline
            and self._resumable_source_manager is None
            and not source_response.lanes
            and source_response.cdc_write_mode is None
            and self._run_uuid is not None
        )

    # The seams below are where a run that writes several tables from one read plugs in (see
    # `lanes.py`). Each default is exactly what a single-table run has always done.

    def _build_s3_writer(self, run_uuid: str | None) -> S3BatchWriter:
        return S3BatchWriter(self._logger, self._job, str(self._schema.id), run_uuid, compression=PARQUET_COMPRESSION)

    def _producer_args(
        self, s3_batch_writer: S3BatchWriter, *, resource_name: str, cdc_write_mode: str | None
    ) -> dict[str, Any]:
        return {
            "database_url": WAREHOUSE_SOURCES_DATABASE_URL,
            "team_id": self._job.team_id,
            "job_id": str(self._job.id),
            "schema_id": str(self._schema.id),
            "source_id": str(self._schema.source_id),
            "resource_name": resource_name,
            "run_uuid": s3_batch_writer.get_run_uuid(),
            "logger": self._logger,
            "primary_keys": self._resource.primary_keys,
            "cdc_write_mode": cdc_write_mode,
            "workflow_id": current_workflow_id(),
            "workflow_run_id": current_workflow_run_id(),
            # Snapshotted on the job when the run started. Empty for every run before
            # destinations, and every run of a team the flag is off for.
            "destination_ids": list(self._job.destination_ids or []),
            "external_destination_ids": list(self._external_destination_ids),
            **self._producer_kwargs,
        }

    def _build_producer(
        self, s3_batch_writer: S3BatchWriter, *, resource_name: str, cdc_write_mode: str | None
    ) -> PostgresProducer:
        return PostgresProducer(
            **self._producer_args(s3_batch_writer, resource_name=resource_name, cdc_write_mode=cdc_write_mode)
        )

    async def _stage_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> int:
        """Write the batch and tell the queue. Returns the rows to count towards usage."""
        batch_result = await asyncio.to_thread(self._s3_batch_writer.write_batch, pa_table, batch_index)
        self._batch_results.append(batch_result)

        # `hold_batch` only inserts the batch this attempt is already holding, not the one it is
        # about to hold. A row from this attempt exists in the queue only once this call flushes one.
        flushes_a_held_batch = self._pg_producer.has_held_batch
        try:
            self._pg_producer.hold_batch(batch_result, cumulative_row_count=row_count)
        except Exception:
            # The insert that failed belongs to the batch before this one. The checkpoint already
            # counts that batch, so no later value of it is safe. The value staged earlier stays valid.
            self._handoff_checkpoint = None
            raise
        if flushes_a_held_batch:
            # This attempt now owns an inserted queue row, so any resume value it stages from here
            # describes rows it holds, not rows an earlier attempt queued.
            self._queued_own_batch = True
        return pa_table.num_rows

    def _total_batches(self) -> int:
        return len(self._batch_results)

    def _consumer_finalizes_this_run(self) -> bool:
        """Whether the load consumer will finalize THIS job, so the workflow must not."""
        return self._total_batches() > 0 or self._sent_resumed_run_finalization

    async def _send_final_batches(self, total_batches: int, row_count: int) -> str | None:
        schema_path = await asyncio.to_thread(self._s3_batch_writer.write_schema)

        self._pg_producer.send_final_batch(
            self._batch_results[-1],
            total_batches=total_batches,
            total_rows=row_count,
            data_folder=self._s3_batch_writer.get_data_folder(),
            schema_path=schema_path,
        )
        return schema_path

    def _release_held_batches(self) -> None:
        """Put every held queue row into the queue now, as a non-final row."""
        if self._pg_producer.release_held_batch():
            # The row this attempt was holding is inserted now, so it owns a queue row of its own.
            self._queued_own_batch = True

    def _mark_first_ever_sync(self) -> None:
        self._pg_producer.is_first_ever_sync = True

    def _maintains_companion_table(self) -> bool:
        """Whether this run's own table is a `_cdc` history table, keyed under its own watermark.

        Read off the resource rather than the lanes: a `cdc_only` run that stands down for
        in-flight batches declares no lanes and runs this base class, and its table is the
        history table all the same.
        """
        return self._resource.cdc_write_mode == SCD2_APPEND_MODE

    def _close_producers(self) -> None:
        self._pg_producer.close()

    def _activate_safe_point(self, items: Any) -> contextlib.ExitStack:
        scope = contextlib.ExitStack()
        if self._resumable_source_manager is not None:
            handler = PipelineSafePointHandler(
                shutdown_monitor=self._shutdown_monitor,
                resumable_source_manager=self._resumable_source_manager,
                has_unwritten_rows=lambda: (
                    self._batcher.should_yield(include_incomplete_chunk=True) or self._pg_producer.has_held_batch
                ),
            )
            scope.enter_context(
                activate_safe_point(handler, covers_framework_checkpoints=source_items_are_framework_output(items))
            )
        return scope

    def _preemption_decision(self) -> PreemptionDecision:
        """Whether another worker can continue this run from now without losing or duplicating rows."""
        if self._schema.is_webhook:
            # The webhook path deletes its staged files after it yields them, so a row that is only
            # in the batcher exists nowhere else.
            return PreemptionDecision(eligible=False, reason="webhook")
        if self._resource.lanes:
            return PreemptionDecision(eligible=False, reason="multiple_tables")
        if self._resumable_source_manager is not None:
            return PreemptionDecision(eligible=True, reason="resumable")
        checkpoint = self._handoff_checkpoint
        carry_over_enabled = self._preemption is not None and self._preemption.watermark_carry_over_enabled
        if checkpoint is not None and not checkpoint.is_void and carry_over_enabled:
            return PreemptionDecision(eligible=True, reason="watermark_carry_over")
        if is_young_first_attempt():
            return PreemptionDecision(eligible=True, reason="young_first_attempt")
        if checkpoint is not None and not checkpoint.is_void:
            return PreemptionDecision(eligible=False, reason="watermark_carry_over_disabled")
        if self._schema.should_use_incremental_field:
            return PreemptionDecision(eligible=False, reason="no_watermark_carry_over")
        return PreemptionDecision(eligible=False, reason="non_resumable_full_refresh")

    async def _fence_abandoned_source(self) -> bool:
        if self._source_resume_manager is None:
            return True
        return await asyncio.to_thread(self._source_resume_manager.revoke_writes, SOURCE_FENCE_TIMEOUT_SECONDS)

    def _source_items(self, items: Any, source_type: str) -> AsyncIterator[Any]:
        if self._preemption is None or self._shutdown_stopwatch is None:
            return async_iterate(items)
        return SourcePreemptor(
            config=self._preemption,
            shutdown_monitor=self._shutdown_monitor,
            stopwatch=self._shutdown_stopwatch,
            decide=self._preemption_decision,
            fence_source=self._fence_abandoned_source,
            source_type=source_type,
            logger=self._logger,
        ).iterate(items)

    def _record_handoff_delay(self, error: WorkerShuttingDownError, source_type: str) -> None:
        if self._shutdown_stopwatch is None or not activity.in_activity():
            return
        delay = self._shutdown_stopwatch.elapsed_seconds()
        if delay is not None:
            mode = "preempted" if isinstance(error, SourcePreemptedError) else "cooperative"
            get_shutdown_handoff_delay_metric(source_type, mode).record(delay)

    async def _commit_resume_state(self) -> None:
        if self._resumable_source_manager is None:
            return
        if self._resumable_source_manager.has_staged_state():
            # The cursor about to commit says every row yielded before it is loadable. A batch whose
            # queue row is still held is not, so a crash between the commit and the next insert
            # would resume past rows the loader never hears about.
            self._release_held_batches()
        await asyncio.to_thread(self._resumable_source_manager.commit)

    async def _stage_handoff_resume_value(self, *, force: bool = False) -> None:
        """Persist the checkpoint's value. Call it only when every observed batch has its queue row.

        Until this attempt queues a batch of its own, the value is still inherited from an earlier
        attempt and describes rows that attempt's queue holds. The owner recorded alongside it
        stays that earlier attempt's run until this one actually queues a row, so a later zero-batch
        continuation finalizes whichever run truly holds the queued rows.
        """
        if self._handoff_checkpoint is None:
            return
        resume_value = self._handoff_checkpoint.resume_value
        # None (the common case) means "whichever run stages this", resolved against `run_uuid` on
        # the model side. Only the inheritance window - before this attempt has queued a batch of
        # its own - needs an explicit owner, so a zero-batch continuation still finalizes the run
        # that holds the rows instead of this one, which holds none yet.
        owner_run_uuid = None if self._queued_own_batch else self._resumed_incremental_run_uuid
        if (
            not force
            and resume_value == self._staged_handoff_resume_value
            and owner_run_uuid == self._staged_handoff_resume_owner
        ):
            return
        await database_sync_to_async_pool(self._schema.stage_handoff_resume_value)(
            self._s3_batch_writer.get_run_uuid(), resume_value, owner_run_uuid
        )
        self._staged_handoff_resume_value = resume_value
        self._staged_handoff_resume_owner = owner_run_uuid

    async def _advance_handoff_checkpoint(self, pa_table: pa.Table) -> None:
        if self._handoff_checkpoint is None:
            return
        # Staging this batch inserted the queue row of the batch before it, so the value from before
        # this batch is safe now. The row of this batch is still held back.
        await self._stage_handoff_resume_value()
        if pa_table.num_rows > 0:
            self._handoff_checkpoint.observe(self._batch_range_reader.read(pa_table))
        if self._handoff_checkpoint.resume_value is None:
            # The checkpoint became void. The next attempt must not use the value staged earlier.
            await self._stage_handoff_resume_value()

    async def run(self) -> PipelineResult:
        pa_memory_pool = pa.default_memory_pool()

        resumes_source_cursor = (
            self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        )
        should_resume = resumes_source_cursor or self._continues_incremental_handoff
        source_is_resumable = self._resumable_source_manager is not None

        if resumes_source_cursor:
            await self._logger.ainfo("V3 Pipeline: Resumable source detected - attempting to resume previous import")
        elif self._continues_incremental_handoff:
            await self._logger.ainfo("V3 Pipeline: Continuing the incremental import after its last queued batch")

        team_id_str = str(self._job.team_id)
        schema_id_str = str(self._schema.id)
        source_type = self._source.source_type if self._source else "unknown"
        sync_type = self._pg_producer.sync_type

        # Recorded where extraction begins, so one observation is one attempt that actually did
        # work. A rising distribution means runs are restarting and re-extracting what earlier
        # attempts already staged.
        if activity.in_activity():
            get_run_attempt_metric(source_type, current_import_attempt_cause()).record(self._attempt)

        start_time = time.perf_counter()
        status = "success"

        await self._logger.ainfo(
            "V3 Pipeline: Extraction starting",
            run_uuid=self._s3_batch_writer.get_run_uuid(),
            sync_type=sync_type,
            is_incremental=self._is_incremental,
            is_resume=should_resume,
            is_first_ever_sync=self._delta_table_ref.is_first_sync,
            reset_pipeline=self._reset_pipeline,
        )

        try:
            await self._sinks.clear()

            # v3 stages the incremental cursor until job completion, so a retried attempt
            # re-extracts from batch 0 and the previous attempt's count must not be kept.
            await reset_rows_synced_if_needed(self._job, should_resume)

            validate_incremental_sync(
                self._is_incremental,
                self._resource,
                is_first_sync=self._table is None or self._reset_pipeline,
            )

            await persist_primary_keys(self._schema, self._resource, self._is_incremental, self._logger)

            await setup_row_tracking_with_billing_check(
                self._job.team_id,
                self._schema,
                self._resource,
                self._source,
                self._logger,
                billable=self._job.billable,
            )

            py_table = None
            row_count = 0
            chunk_index = 0

            # On retry (attempt > 1) skip reset_table() - the consumer-side batch-0
            # overwrite handles it. Wiping the delta table mid-retry while the consumer
            # is loading the previous attempt's batches causes data loss.
            if self._attempt <= 1:
                # Revive a corrupt-`_delta_log` table before extraction so it self-heals in this run
                # instead of looping forever (an interrupted repartition swap or OOM-crashed merge).
                await handle_corrupted_delta_log(self._schema, self._job, self._delta_table_ref, self._logger)

                await handle_reset_or_full_refresh(
                    self._reset_pipeline,
                    should_resume,
                    self._schema,
                    self._delta_table_ref,
                    self._logger,
                    webhook_only=self._resource.webhook_only,
                )

            is_fresh_sync = self._delta_table_ref.is_first_sync or self._schema.table is None
            if is_fresh_sync:
                self._mark_first_ever_sync()

            # Defensive pre-write compaction so a sync that arrived at a fragmented Delta
            # target cleans up before adding more small files; see DeltaMaintenance.run_scheduled.
            if not is_fresh_sync:
                await DeltaMaintenance(self._delta_table_ref).run_scheduled(
                    self._schema,
                    is_cdc_companion=self._maintains_companion_table(),
                )

            async def stage_remaining_rows() -> None:
                nonlocal chunk_index, row_count
                while self._batcher.should_yield(include_incomplete_chunk=True):
                    py_table = self._batcher.get_table()
                    row_count += py_table.num_rows
                    await self._process_batch(
                        pa_table=py_table,
                        batch_index=chunk_index,
                        row_count=row_count,
                    )

                    if activity.in_activity():
                        get_rows_extracted_metric(team_id_str, schema_id_str, source_type).add(py_table.num_rows)
                        get_batches_produced_metric(team_id_str, schema_id_str).add(1)

                    chunk_index += 1
                # Every yielded row is staged now, so whatever the source staged last is safe.
                await self._commit_resume_state()

            if self._attempt > 1:
                # Written before this attempt can replace the queue rows of an earlier attempt, so the
                # attempt after this one never reads a value that describes rows which are gone.
                await self._stage_handoff_resume_value(force=True)

            items = self._resource.items()
            safe_point_scope = self._activate_safe_point(items)
            source_items = self._source_items(items, source_type)
            awaiting_source = True
            try:
                async for item in source_items:
                    awaiting_source = False
                    py_table = None

                    record_source_item_stats(
                        item,
                        source_type=source_type,
                        logger=self._logger,
                        team_id=self._job.team_id,
                        schema_name=self._schema.name,
                    )

                    self._batcher.batch(item)

                    # A single batched table may be split into several when a string/binary/list
                    # column would otherwise overflow a 32-bit offset, so drain every ready chunk.
                    wrote_chunk = False
                    while self._batcher.should_yield():
                        py_table = self._batcher.get_table()
                        row_count += py_table.num_rows

                        await self._process_batch(
                            pa_table=py_table,
                            batch_index=chunk_index,
                            row_count=row_count,
                        )
                        wrote_chunk = True

                        if activity.in_activity():
                            get_rows_extracted_metric(team_id_str, schema_id_str, source_type).add(py_table.num_rows)
                            get_batches_produced_metric(team_id_str, schema_id_str).add(1)

                        chunk_index += 1

                        cleanup_memory(pa_memory_pool, py_table)
                        py_table = None

                    # A staged batch is what makes the cursor safe to persist: after a buffered-only item
                    # it would skip rows that never landed, and after the shutdown check it would never land.
                    if wrote_chunk:
                        await self._commit_resume_state()

                    if should_check_shutdown(self._schema, self._resource, self._reset_pipeline, source_is_resumable):
                        if self._handoff_checkpoint is not None and self._shutdown_monitor.is_worker_shutdown():
                            # The next attempt continues after the last staged batch, so staging the
                            # buffered rows now keeps it from extracting them again. A source with its
                            # own cursor does not get this: its cursor can be behind the buffered rows,
                            # and staging them would load them a second time after the resume.
                            await stage_remaining_rows()
                        self._shutdown_monitor.raise_if_is_worker_shutdown()
                    awaiting_source = True
            except SourcePreemptedError:
                # The source is still inside a call, so the cursor it staged can cover rows it did
                # not yield yet. That cursor must not commit, and the buffered rows of a source with
                # its own cursor stay unwritten: the committed cursor is behind them, so the next
                # attempt reads them again. A run that continues after its last staged batch has no
                # such cursor, so its buffered rows are staged.
                if self._handoff_checkpoint is not None:
                    await stage_remaining_rows()
                raise
            except Exception:
                # A resumable source that ends its own attempt (a page or time budget) has staged a
                # cursor for rows the batcher still holds. Staging them lets that cursor commit, so the
                # next attempt continues from it instead of restarting the sweep.
                if awaiting_source and source_is_resumable:
                    try:
                        await stage_remaining_rows()
                    except Exception:
                        await self._logger.aexception("Failed to stage the rows buffered before the source error")
                raise
            finally:
                safe_point_scope.close()
                if isinstance(source_items, AsyncGenerator) and self._preemption is not None:
                    # Stops the thread of the source now. A loop that ended early left it waiting.
                    await source_items.aclose()

            await stage_remaining_rows()
            await self._finalize(row_count=row_count)

            # With zero batches, `_finalize` sent no final-batch notification, so the load
            # consumer will never hear about this run and cannot finalize it — the workflow must.
            # See the PipelineResult docstring for the full ownership contract.
            consumer_will_hear_about_this_run = self._consumer_finalizes_this_run()

            result = PipelineResult(
                should_trigger_cdp_producer=await self._sinks.cdp_producer.should_run(),
                consumer_manages_job_status=consumer_will_hear_about_this_run,
            )
            if self._resource.on_complete is not None:
                try:
                    await asyncio.to_thread(self._resource.on_complete)
                except Exception:
                    await self._logger.aexception("Failed to clean up completed source state")
            return result
        except Exception as error:
            status = "error"
            self._logger.exception("V3 Pipeline: Extraction failed")
            # Same queue state a failed run has always left: every staged batch has a row, so an
            # incremental run's loadable tail can still drain (see `_drainable_after_failure`).
            try:
                self._release_held_batches()
            except Exception:
                self._logger.exception("V3 Pipeline: Failed to enqueue the held batch after the extraction error")
            else:
                # Every staged batch has its queue row now, so the next attempt can continue after them.
                try:
                    await self._stage_handoff_resume_value()
                except Exception:
                    self._logger.exception("V3 Pipeline: Failed to record where the next attempt can continue")
            if isinstance(error, WorkerShuttingDownError):
                self._record_handoff_delay(error, source_type)
            raise
        finally:
            duration = time.perf_counter() - start_time
            if activity.in_activity():
                get_pipeline_run_duration_metric(team_id_str, source_type, sync_type, status).record(duration)

            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_v3_extraction_completed",
                properties={
                    "team_id": self._job.team_id,
                    "schema_id": str(self._schema.id),
                    "source_type": source_type,
                    "sync_type": sync_type,
                    "status": status,
                    "duration_seconds": duration,
                    "total_batches": self._total_batches(),
                    "total_rows": row_count if "row_count" in locals() else 0,
                },
            )

            self._logger.debug("V3 Pipeline: Cleaning up resources")
            del self._resource
            del self._s3_batch_writer
            self._close_producers()
            del self._pg_producer

            cleanup_memory(pa_memory_pool, py_table if "py_table" in locals() else None)

    async def _process_batch(self, pa_table: pa.Table, batch_index: int, row_count: int) -> None:
        pa_table = _append_debug_column_to_pyarrows_table(pa_table, self._load_id)
        pa_table = normalize_table_column_names(pa_table)

        if self._uses_delta_write_column_selection:
            pa_table = await observe_and_project_table(
                pa_table,
                self._schema.enabled_columns,
                self._resource.primary_keys,
                self._schema.incremental_field,
                [
                    *(self._schema.partitioning_keys_override or []),
                    *(self._schema.partitioning_keys or []),
                    *(self._resource.partition_keys or []),
                ],
                self._observed_columns,
                self._logger,
                "V3 Pipeline: Dropped non-enabled columns before write",
            )

        pa_table = evolve_pyarrow_schema(pa_table, None)
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        # Converge this batch onto the column types earlier batches in this run already used,
        # and backfill columns they had that this one doesn't. The cursor column is named both
        # raw and normalized because `normalize_table_column_names` above may have renamed it.
        cursor_columns = (
            {self._schema.incremental_field, normalize_column_name(self._schema.incremental_field)}
            if self._schema.incremental_field
            else set()
        )
        pa_table, self._accumulated_pa_schema = reconcile_batch_to_accumulated_schema(
            pa_table, self._accumulated_pa_schema, self._logger, protected_columns=cursor_columns
        )

        tracked_rows = await self._stage_batch(pa_table, batch_index, row_count)

        self._internal_schema.add_pyarrow_table(pa_table)

        await self._sinks.stage_chunk(batch_index, pa_table)

        incremental_values = await update_incremental_field_values(
            self._schema,
            pa_table,
            self._resource,
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
            self._logger,
            log_prefix="V3 Pipeline: ",
            staging_run_uuid=self._s3_batch_writer.get_run_uuid(),
        )
        self._last_incremental_field_value = incremental_values.last_value
        self._earliest_incremental_field_value = incremental_values.earliest_value
        await self._advance_handoff_checkpoint(pa_table)

        await update_row_tracking_after_batch(
            str(self._job.id), self._job.team_id, self._schema.id, tracked_rows, self._logger
        )

    async def _stamp_full_run(self) -> None:
        """Record that this run took the full extraction path, for the fast-return valve.

        Writes only `last_full_run_at`.
        `last_synced_at` is deliberately left alone: it feeds data freshness, the schemas UI and
        the signals watermark (`partition_field > last_synced_at`), so moving it on a run that
        loaded nothing would narrow the next run's signal window.

        Best-effort: a bookkeeping failure must not fail an otherwise successful sync, which is
        how the observed-columns write above treats the same risk.
        """
        try:
            await database_sync_to_async_pool(update_sync_type_config_keys)(
                self._schema.id,
                self._job.team_id,
                updates={"last_full_run_at": datetime.datetime.now(datetime.UTC).isoformat()},
            )
        except Exception:
            await self._logger.aexception("V3 Pipeline: Failed to stamp last_full_run_at")

    async def _finalize(self, row_count: int) -> None:
        # Column-picker bookkeeping — a failure here must not fail an otherwise successful sync.
        if self._observed_columns:
            observed = list(self._observed_columns.values())
            try:
                await database_sync_to_async_pool(update_sync_type_config_keys)(
                    self._schema.id,
                    self._job.team_id,
                    mutate=lambda config: merge_observed_columns_into_schema_metadata(config, observed),
                )
            except Exception:
                await self._logger.aexception("V3 Pipeline: Failed to persist observed columns into schema_metadata")

        total_batches = self._total_batches()

        if total_batches == 0:
            if self._continues_incremental_handoff:
                if self._resumed_incremental_run_uuid is None:
                    raise RuntimeError("A resumed incremental import has no queue run to finalize")
                await asyncio.to_thread(
                    self._pg_producer.send_final_batch_for_resumed_run, self._resumed_incremental_run_uuid
                )
                self._sent_resumed_run_finalization = True
                return

            # A zero-batch run still ran the full extraction, which is what the fast-return
            # valve counts. Post-load stamps this on every other path but never runs here: with
            # no batches the load consumer is never notified. Without this a v3 schema whose
            # source stays quiet could never satisfy `_fast_return_eligible`.
            await self._stamp_full_run()
            # No batch reaches the loader, so nothing would promote a staged cursor. With no rows
            # outstanding the cursor is already safe to store.
            await commit_source_cursor(
                self._source_cursor_manager,
                self._schema,
                self._logger,
                staging_run_uuid=None,
                log_prefix="V3 Pipeline: ",
            )
            self._logger.debug("V3 Pipeline: No batches extracted, skipping finalization")
            return

        self._logger.info(
            f"V3 Pipeline: Finalizing extraction",
            total_batches=total_batches,
            total_rows=row_count,
        )

        # Stage the watermark before the final-batch notification. The load consumer promotes the
        # staged slot when that batch completes, and a slot staged after that is never promoted.
        await finalize_desc_sort_incremental_value(
            self._resource,
            self._schema,
            self._last_incremental_field_value,
            self._logger,
            log_prefix="V3 Pipeline: ",
            staging_run_uuid=self._s3_batch_writer.get_run_uuid(),
        )
        await commit_source_cursor(
            self._source_cursor_manager,
            self._schema,
            self._logger,
            staging_run_uuid=self._s3_batch_writer.get_run_uuid(),
            log_prefix="V3 Pipeline: ",
        )

        schema_path = await self._send_final_batches(total_batches, row_count)

        # initial_sync_complete is set by the loader's post-load after data lands in Delta.

        await self._logger.ainfo(
            f"V3 Pipeline: Extraction complete",
            total_batches=total_batches,
            total_rows=row_count,
            base_folder=self._s3_batch_writer.get_base_folder(),
            schema_path=schema_path,
        )
