import sys
import time
from typing import TYPE_CHECKING, Any, Generic, Literal

import pyarrow as pa
import deltalake as deltalake
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    process_incremental_value,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    advance_xmin_state,
    cleanup_memory,
    handle_corrupted_delta_log,
    handle_reset_or_full_refresh,
    persist_primary_keys,
    reset_rows_synced_if_needed,
    resolve_primary_keys,
    setup_row_tracking_with_billing_check,
    should_check_shutdown,
    update_incremental_field_values,
    update_row_tracking_after_batch,
    validate_incremental_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import (
    run_post_load_operations,
    supports_partial_data_loading,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    _append_debug_column_to_pyarrows_table,
    _handle_null_columns_with_definitions,
    evolve_pyarrow_schema,
    merge_observed_columns_into_schema_metadata,
    normalize_table_column_names,
    observe_and_project_table,
    source_uses_delta_write_column_selection,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.async_iterate import async_iterate
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import DeltaMaintenance
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import setup_partitioning
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.sinks import (
    PipelineSinks,
    build_pipeline_sinks,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.table_stats import record_source_item_stats
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    validate_schema_and_update_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    ResumableData,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
        ImportJobModels,
    )


class PipelineNonDLT(Generic[ResumableData]):
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
    _internal_schema = HogQLSchema()
    _sinks: PipelineSinks
    _batcher: Batcher
    _load_id: int

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
    ) -> None:
        self._resource = source_response
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
        self._is_incremental = models.schema.is_incremental or models.schema.is_webhook or models.schema.is_xmin

        # Mirrors the `is_first_sync` passed to `validate_incremental_sync` below: a schema with no
        # `DataWarehouseTable` row yet is a fresh (or retried-fresh) sync even when a Delta table
        # already exists in storage from an earlier attempt at writing the same first sync. Without
        # this, the writer's own is-first-sync detection (no physical table found) never fires for
        # that case, and an incremental write with no primary key wrongly takes the merge path
        # instead of overwriting, raising MissingPrimaryKeysException on an otherwise-healthy sync.
        self._delta_table_ref = DeltaTableRef(
            self._resource_name, self._job, self._logger, is_first_sync=self._table is None
        )
        self._resumable_source_manager = resumable_source_manager
        # A source can shrink the batcher chunk (e.g. document sources with large rows) so the
        # source->Arrow conversion doesn't materialise an oversized table; None falls back to defaults.
        self._batcher = Batcher(
            self._logger,
            chunk_size=source_response.chunk_size,
            chunk_size_bytes=source_response.chunk_size_bytes,
            source_type=self._source.source_type,
            team_id=self._job.team_id,
            schema_name=self._schema.name,
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
        self._shutdown_monitor = shutdown_monitor
        self._last_incremental_field_value: Any = None
        self._earliest_incremental_field_value: Any = process_incremental_value(
            models.schema.incremental_field_earliest_value, models.schema.incremental_field_type
        )
        # SQL sources project enabled_columns in their SELECT and own schema_metadata via
        # introspection; managed-schema sources don't allow selection. Everything else gets the
        # Delta-write-side drop plus observed-columns capture so the column picker has a catalog.
        self._uses_delta_write_column_selection = source_uses_delta_write_column_selection(models.source.source_type)
        self._observed_columns: dict[str, dict[str, Any]] = {}

    async def run(self) -> PipelineResult:
        pa_memory_pool = pa.default_memory_pool()

        should_resume = self._resumable_source_manager is not None and self._resumable_source_manager.can_resume()
        source_is_resumable = self._resumable_source_manager is not None
        if should_resume:
            await self._logger.ainfo("Resumable source detected - attempting to resume previous import")

        try:
            await self._sinks.clear()

            await reset_rows_synced_if_needed(self._job, self._is_incremental, self._reset_pipeline, should_resume)

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

            # Revive a corrupt-`_delta_log` table (from an interrupted repartition swap or OOM-crashed
            # merge) before extraction so it self-heals in this run instead of looping forever.
            await handle_corrupted_delta_log(self._schema, self._job, self._delta_table_ref, self._logger)

            await handle_reset_or_full_refresh(
                self._reset_pipeline,
                should_resume,
                self._schema,
                self._delta_table_ref,
                self._logger,
                webhook_only=self._resource.webhook_only,
            )

            # If the schema has no DWH table, it's a first ever sync
            is_first_ever_sync: bool = self._table is None

            # Defensive pre-write compaction so a sync that arrived at a fragmented
            # Delta target (e.g. earlier attempts that failed before reaching
            # `_post_run_operations`) cleans up before adding more small files. Skipped
            # cheaply when the table is healthy; see DeltaMaintenance.run_scheduled.
            if not is_first_ever_sync:
                await DeltaMaintenance(self._delta_table_ref).run_scheduled(
                    self._schema, partition_count_fallback=self._resource.partition_count
                )

            async for item in async_iterate(self._resource.items()):
                py_table = None

                record_source_item_stats(
                    item,
                    source_type=self._source.source_type,
                    logger=self._logger,
                    team_id=self._job.team_id,
                    schema_name=self._schema.name,
                )

                self._batcher.batch(item)

                # A single batched table may be split into several when a string/binary/list
                # column would otherwise overflow a 32-bit offset, so drain every ready chunk.
                while self._batcher.should_yield():
                    py_table = self._batcher.get_table()

                    row_count += py_table.num_rows

                    await self._process_pa_table(
                        pa_table=py_table,
                        index=chunk_index,
                        resuming_sync=should_resume,
                        row_count=row_count,
                        is_first_ever_sync=is_first_ever_sync,
                    )

                    chunk_index += 1

                    cleanup_memory(pa_memory_pool, py_table)
                    py_table = None

                if should_check_shutdown(self._schema, self._resource, self._reset_pipeline, source_is_resumable):
                    self._shutdown_monitor.raise_if_is_worker_shutdown()

            while self._batcher.should_yield(include_incomplete_chunk=True):
                py_table = self._batcher.get_table()
                row_count += py_table.num_rows
                await self._process_pa_table(
                    pa_table=py_table,
                    index=chunk_index,
                    resuming_sync=should_resume,
                    row_count=row_count,
                    is_first_ever_sync=is_first_ever_sync,
                )
                chunk_index += 1

            await self._persist_observed_columns()

            prepared_queryable_folder = await self._post_run_operations(row_count=row_count)

            await advance_xmin_state(self._resource, self._schema, self._logger)

            result = PipelineResult(should_trigger_cdp_producer=await self._sinks.cdp_producer.should_run())
            if isinstance(prepared_queryable_folder, str):
                result["prepared_queryable_folder"] = prepared_queryable_folder
            return result
        finally:
            # Help reduce the memory footprint of each job. This is best-effort cleanup of
            # whatever `get_delta_table` already cached this run — pop rather than call, so a
            # run that failed before ever fetching the delta table (nothing to release) doesn't
            # make a fresh, unrelated object-storage call here that can itself raise and get
            # captured, obscuring the real import error that's already driving retry
            # classification and the user-facing message.
            await self._logger.adebug("Cleaning up delta table helper")
            delta_table = self._delta_table_ref.get_delta_table.cache_pop(self._delta_table_ref)
            if delta_table:
                del delta_table

            del self._resource
            del self._delta_table_ref

            cleanup_memory(pa_memory_pool, py_table if "py_table" in locals() else None)

    async def _persist_observed_columns(self) -> None:
        """Union the columns the source actually returned into `schema_metadata["columns"]`.

        Bookkeeping for the column picker — a failure here must not fail an otherwise
        successful sync.
        """
        if not self._observed_columns:
            return
        observed = list(self._observed_columns.values())
        try:
            await database_sync_to_async_pool(update_sync_type_config_keys)(
                self._schema.id,
                self._job.team_id,
                mutate=lambda config: merge_observed_columns_into_schema_metadata(config, observed),
            )
        except Exception:
            await self._logger.aexception("Failed to persist observed columns into schema_metadata")

    async def _process_pa_table(
        self, pa_table: pa.Table, index: int, resuming_sync: bool, row_count: int, is_first_ever_sync: bool
    ):
        delta_table = await self._delta_table_ref.get_delta_table()
        previous_file_uris = await self._delta_table_ref.get_file_uris()

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
                "Dropped non-enabled columns before Delta write",
            )

        pa_table = await setup_partitioning(pa_table, delta_table, self._schema, self._resource, self._logger)

        pa_table = evolve_pyarrow_schema(
            pa_table,
            delta_table.schema() if delta_table is not None else None,
            merge_key_columns=[
                *(self._resource.primary_keys or []),
                *(self._schema.partitioning_keys_override or []),
                *(self._schema.partitioning_keys or []),
                *(self._resource.partition_keys or []),
            ],
        )
        pa_table = _handle_null_columns_with_definitions(pa_table, self._resource)

        write_type: Literal["incremental", "full_refresh", "append"] = "full_refresh"
        if self._schema.is_incremental or self._schema.is_webhook or self._schema.is_xmin:
            write_type = "incremental"
        elif self._schema.is_append:
            write_type = "append"

        should_overwrite_table = index == 0 and not resuming_sync

        delta_table = await DeltaWriter(self._delta_table_ref).write(
            pa_table,
            write_type,
            should_overwrite_table=should_overwrite_table,
            primary_keys=self._resource.primary_keys,
        )

        self._internal_schema.add_pyarrow_table(pa_table)

        await self._sinks.stage_chunk(index, pa_table)

        incremental_values = await update_incremental_field_values(
            self._schema,
            pa_table,
            self._resource,
            self._last_incremental_field_value,
            self._earliest_incremental_field_value,
            self._logger,
        )
        self._last_incremental_field_value = incremental_values.last_value
        self._earliest_incremental_field_value = incremental_values.earliest_value

        await update_row_tracking_after_batch(
            self._job.id, self._job.team_id, self._schema.id, pa_table.num_rows, self._logger
        )

        # if it's the first ever sync for this schema and the source supports partial data loading, we make the delta
        # table files available for querying and create the data warehouse table, so that the user has some data
        # available to start using
        # TODO - enable this for all source types
        if is_first_ever_sync and supports_partial_data_loading(self._schema):
            file_uris = await self._delta_table_ref.get_file_uris()

            await self._process_partial_data(
                previous_file_uris=previous_file_uris,
                file_uris=file_uris,
                row_count=row_count,
                chunk_index=index,
            )

    async def _process_partial_data(
        self, previous_file_uris: list[str], file_uris: list[str], row_count: int, chunk_index: int
    ):
        await self._logger.adebug(
            "Source supports partial data loading and is first ever sync -> "
            "making delta table files available for querying and creating data warehouse table"
        )
        if chunk_index == 0:
            new_file_uris = file_uris
        else:
            new_file_uris = list(set(file_uris) - set(previous_file_uris))
            # in theory, we should always be appending files for a first time sync but we just check that this is the
            # case in case we update this assumption
            files_modified = set(previous_file_uris) - set(file_uris)
            if len(files_modified) > 0:
                await self._logger.awarning(
                    "Should always be appending delta table files for a first time sync but found modified files!"
                )
                capture_exception(
                    Exception(
                        "Should always be appending delta table files for a first time sync but found modified files!"
                    )
                )
                return

        await self._logger.adebug(f"Adding {len(new_file_uris)} S3 files to query folder")
        folder_path = await database_sync_to_async_pool(self._job.folder_path)()
        queryable_folder = await prepare_s3_files_for_querying(
            folder_path=folder_path,
            table_name=self._resource_name,
            file_uris=new_file_uris,
            # delete existing files if it's the first chunk, otherwise we'll just append to the existing files
            delete_existing=chunk_index == 0,
            use_timestamped_folders=False,
            logger=self._logger,
        )
        await self._logger.adebug("Validating schema and updating table")
        await validate_schema_and_update_table(
            run_id=str(self._job.id),
            team_id=self._job.team_id,
            schema_id=self._schema.id,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        )

    async def _post_run_operations(self, row_count: int) -> str | None:
        return await run_post_load_operations(
            job=self._job,
            schema=self._schema,
            source=self._source,
            delta_table_ref=self._delta_table_ref,
            row_count=row_count,
            table_schema_dict=self._internal_schema.to_hogql_types(),
            resource_name=self._resource_name,
            logger=self._logger,
            last_incremental_field_value=self._last_incremental_field_value,
            resource=self._resource,
            allow_zero_row_skip=True,
        )


def _estimate_size(obj: Any) -> int:
    if isinstance(obj, dict):
        return sys.getsizeof(obj) + sum(_estimate_size(k) + _estimate_size(v) for k, v in obj.items())
    elif isinstance(obj, list | tuple | set):
        return sys.getsizeof(obj) + sum(_estimate_size(i) for i in obj)
    else:
        return sys.getsizeof(obj)
