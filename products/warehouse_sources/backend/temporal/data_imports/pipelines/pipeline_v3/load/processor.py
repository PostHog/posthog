import uuid
import socket
import dataclasses
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Literal

from django.conf import settings
from django.db import close_old_connections, transaction

import pyarrow as pa
import deltalake as deltalake
import structlog
import pyarrow.compute as pc
import posthoganalytics
from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from posthog.exceptions_capture import capture_exception
from posthog.utils import get_machine_id

from products.data_warehouse.backend.facade.api import update_external_job_status
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_OP_COLUMN,
    SCD2_VALID_FROM_COLUMN,
    SCD2_VALID_TO_COLUMN,
    TOAST_OMITTED_COLUMN,
    enrich_delete_rows,
    enrich_toast_omitted_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_resolution import (
    has_engine_seq,
    resolve_batch,
    verify_delete_enrichment,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import (
    PostLoadResult,
    run_post_load_operations,
    supports_partial_data_loading,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
    evolve_pyarrow_schema,
    pyarrow_schema_from_arrow_exportable,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.auto_widen_resync import (
    maybe_schedule_auto_widen_resync,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import get_governor
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.rss_sampler import RssPeakSampler
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.scd2 import Scd2DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import (
    DeltaWriter,
    commit_members_tag,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    post_load_phase,
    record_post_load_phases,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    validate_schema_and_update_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.coalescing import (
    CoalesceMember,
    runs_in_order,
    set_violation,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.batch_steps import (
    BatchStepTimer,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
    is_batch_already_processed,
    mark_batch_as_processed,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL,
    CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL,
    DELTA_ROWS_WRITTEN_TOTAL,
    DELTA_WRITE_DURATION_SECONDS,
    IDEMPOTENCY_HIT_TOTAL,
    PARQUET_READ_DURATION_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.table_handles import (
    GROUP_TABLE_HANDLES,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import (
    ExportSignalMessage,
    SyncTypeLiteral,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import (
    read_parquet,
    read_parquet_first_values,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    release_v3_pipeline_lock,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import finish_row_tracking
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import merge_cursor_payloads
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying
from products.warehouse_sources.backend.temporal.data_imports.workload_report import report_phase, workload_reporting
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.warehouse_sources_queue.backend.core.batch_consumer import CoalescingDeclined, OwnershipLostError

logger = structlog.get_logger(__name__)

# Batch interval at which `batch_written_to_delta_lake` carries a file count. Frequent enough to
# show a table fragmenting over a multi-hundred-batch load, rare enough that the listing it needs
# stays off the per-batch path.
FILE_COUNT_LOG_SAMPLE_EVERY = 100


def _get_write_type(sync_type: SyncTypeLiteral) -> Literal["incremental", "full_refresh", "append"]:
    """Convert sync type to write type for DeltaTableRef."""
    if sync_type in ("incremental", "cdc"):
        return "incremental"
    elif sync_type == "append":
        return "append"
    return "full_refresh"


def _read_existing_rows_by_first_pk(
    existing_delta_table: deltalake.DeltaTable,
    first_pk: str,
    first_components: list[Any],
) -> pa.Table:
    """Read the existing rows whose `first_pk` value is in `first_components`.

    Prefers Delta filter pushdown (prunes files, cheap). pyarrow >= 21 materializes
    string columns as `string_view`, whose `equal`/`greater_equal` compute kernels are
    unimplemented, so pushing an `in` predicate down onto a string primary key raises
    `ArrowNotImplementedError`. When that happens, read the table and filter in PyArrow
    after casting the key to `string`, which has working kernels.
    """
    try:
        return existing_delta_table.to_pyarrow_table(filters=[(first_pk, "in", first_components)])
    except pa.lib.ArrowNotImplementedError:
        logger.warning("cdc_delete_enrichment_pushdown_fallback", primary_key=first_pk)
        existing = existing_delta_table.to_pyarrow_table()
        key = existing.column(first_pk).cast(pa.string())
        wanted = pa.array(first_components, pa.string())
        return existing.filter(pc.is_in(key, value_set=wanted))


def _enrich_cdc_rows(
    pa_table: pa.Table,
    *,
    primary_keys: list[str] | None,
    cdc_write_mode: str | None,
    existing_delta_table: deltalake.DeltaTable | None,
    batch_index: int,
    verify_deletes: bool = False,
) -> pa.Table:
    """Cross-batch CDC enrichment against the existing DeltaLake state.

    Batch-internal enrichment was already applied in the extraction activity; this
    fills what only the target table knows:
    - DELETE rows with no preceding INSERT/UPDATE for the same PK in the batch.
    - Unchanged-TOAST (omitted) UPDATE columns whose last value is not in the batch.

    Always strips TOAST_OMITTED_COLUMN before returning — it is transport metadata
    for this enrichment and must never reach DeltaLake.
    """
    if cdc_write_mode is None:
        return pa_table

    if primary_keys and existing_delta_table is not None and CDC_OP_COLUMN in pa_table.column_names:
        present_pks = [col for col in primary_keys if col in pa_table.column_names]
        if present_pks:
            ops = pa_table.column(CDC_OP_COLUMN).to_pylist()
            pk_arrays = [pa_table.column(col).to_pylist() for col in present_pks]
            delete_key_set: set[tuple[Any, ...]] = set()
            for i, op in enumerate(ops):
                if op == "D":
                    delete_key_set.add(tuple(arr[i] for arr in pk_arrays))

            toast_key_set: set[tuple[Any, ...]] = set()
            if TOAST_OMITTED_COLUMN in pa_table.column_names:
                omitted_lists = pa_table.column(TOAST_OMITTED_COLUMN).to_pylist()
                for i, omitted in enumerate(omitted_lists):
                    if omitted:
                        toast_key_set.add(tuple(arr[i] for arr in pk_arrays))

            enrich_key_set = delete_key_set | toast_key_set
            if enrich_key_set:
                logger.debug(
                    "cdc_delete_enrichment",
                    delete_row_count=len(delete_key_set),
                    toast_omitted_row_count=len(toast_key_set),
                    primary_key_count=len(present_pks),
                    cdc_write_mode=cdc_write_mode,
                    batch_index=batch_index,
                )
                # Delta-rs: single-column IN avoids tuple filters (weak NULL semantics).
                # For composite PKs that IN is a superset — narrow in PyArrow below.
                first_pk = present_pks[0]
                first_components = list({t[0] for t in enrich_key_set})
                existing_rows = _read_existing_rows_by_first_pk(existing_delta_table, first_pk, first_components)

                # For composite PKs the IN filter is a superset — narrow to exact matches.
                if len(present_pks) > 1 and existing_rows.num_rows > 0:
                    if all(col in existing_rows.column_names for col in present_pks):
                        ex_pk_arrays = [existing_rows.column(col).to_pylist() for col in present_pks]
                        match_indices = [
                            j
                            for j in range(existing_rows.num_rows)
                            if tuple(arr[j] for arr in ex_pk_arrays) in enrich_key_set
                        ]
                        # Explicit int64 so an empty result doesn't infer a null-typed index array.
                        existing_rows = existing_rows.take(pa.array(match_indices, type=pa.int64()))
                    else:
                        existing_rows = existing_rows.take(pa.array([], type=pa.int64()))

                # For SCD2 tables, keep only "current" rows (valid_to IS NULL) so we
                # enrich with the most recent state rather than a historical one.
                if (
                    cdc_write_mode == "scd2_append"
                    and existing_rows.num_rows > 0
                    and SCD2_VALID_TO_COLUMN in existing_rows.column_names
                ):
                    existing_rows = existing_rows.filter(pc.is_null(existing_rows.column(SCD2_VALID_TO_COLUMN)))

                # TOAST fill first so DELETE enrichment copies resolved values,
                # not the nulls standing in for omitted columns.
                pa_table = enrich_toast_omitted_rows(pa_table, primary_keys, existing_rows)
                pa_table = enrich_delete_rows(pa_table, primary_keys, existing_rows)

                # Only place the previous state is still in hand to compare against.
                if verify_deletes and delete_key_set:
                    report = verify_delete_enrichment(pa_table, present_pks, existing_rows)
                    if not report.ok:
                        CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL.inc(report.rows_with_nulled_columns)
                        logger.warning(
                            "cdc_delete_enrichment_violation",
                            delete_rows_checked=report.delete_rows_checked,
                            rows_with_nulled_columns=report.rows_with_nulled_columns,
                            columns=list(report.columns),
                            cdc_write_mode=cdc_write_mode,
                            batch_index=batch_index,
                        )

    if TOAST_OMITTED_COLUMN in pa_table.column_names:
        pa_table = pa_table.drop_columns([TOAST_OMITTED_COLUMN])

    return pa_table


def _resolve_cdc_positions(
    pa_table: pa.Table,
    *,
    primary_keys: list[str],
    cdc_write_mode: str | None,
) -> pa.Table:
    """Collapse a merge batch to one row per key — the write engine rejects duplicates."""
    if not has_engine_seq(pa_table):
        return pa_table

    pa_table, stats = resolve_batch(
        pa_table,
        primary_keys,
        cdc_write_mode=cdc_write_mode,
    )
    if stats.duplicate_key:
        CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL.labels(reason="duplicate_key").inc(stats.duplicate_key)

    return pa_table


def _apply_partitioning(
    export_signal: ExportSignalMessage,
    pa_table: pa.Table,
    existing_delta_table: deltalake.DeltaTable | None,
    schema: ExternalDataSchema,
) -> pa.Table:
    """Apply partitioning to the table if configured."""
    partition_keys = export_signal.partition_keys

    if not partition_keys:
        logger.debug("No partition keys, skipping partitioning")
        return pa_table

    if existing_delta_table:
        # Check the table's *partition columns* — not its schema columns. A delta
        # table can contain `_ph_partition_key` in its schema without being
        # partitioned by it (e.g. leftover from a prior write that included the
        # column but was committed with `partition_by=None`). Writing with
        # `partition_by=PARTITION_KEY` in that case raises
        # `DeltaError: Specified table partitioning does not match table partitioning`.
        partition_columns = getattr(existing_delta_table.metadata(), "partition_columns", None) or []
        if PARTITION_KEY not in partition_columns:
            logger.debug("Delta table already exists without partitioning, skipping partitioning")
            return pa_table

    partition_result = append_partition_key_to_table(
        table=pa_table,
        partition_count=export_signal.partition_count,
        partition_size=export_signal.partition_size,
        partition_keys=partition_keys,
        partition_mode=export_signal.partition_mode,
        partition_format=export_signal.partition_format,
        logger=logger,
    )

    if partition_result is not None:
        pa_table = partition_result.table

        if (
            not schema.partitioning_enabled
            or schema.partition_mode != partition_result.partition_mode
            or schema.partition_format != partition_result.partition_format
            or schema.partitioning_keys != partition_result.partition_keys
        ):
            logger.debug(
                f"Setting partitioning_enabled on schema with: partition_keys={partition_keys}. partition_count={export_signal.partition_count}. partition_mode={partition_result.partition_mode}. partition_format={partition_result.partition_format}"
            )
            schema.set_partitioning_enabled(
                partition_result.partition_keys,
                export_signal.partition_count,
                export_signal.partition_size,
                partition_result.partition_mode,
                partition_result.partition_format,
            )

    return pa_table


def _partial_data_loading_applies(export_signal: ExportSignalMessage, schema: ExternalDataSchema) -> bool:
    """Whether this batch feeds partial data loading (first-ever sync, Stripe only).

    Read before the write as well as after: `previous_file_uris` only exists to serve this
    feature, and collecting it means listing every file in the table.
    """
    return export_signal.is_first_ever_sync and supports_partial_data_loading(schema)


async def _handle_partial_data_loading(
    export_signal: ExportSignalMessage,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table: deltalake.DeltaTable,
    previous_file_uris: list[str],
    internal_schema: HogQLSchema,
) -> None:
    """Make data available for querying during first-ever sync for Stripe sources."""
    if not _partial_data_loading_applies(export_signal, schema):
        return

    current_file_uris = delta_table.file_uris()

    if export_signal.batch_index == 0:
        new_file_uris = current_file_uris
    else:
        new_file_uris = list(set(current_file_uris) - set(previous_file_uris))
        modified_files = set(previous_file_uris) - set(current_file_uris)
        if modified_files:
            logger.warning(
                "Found modified files during first sync, skipping partial data loading",
                batch_index=export_signal.batch_index,
                modified_count=len(modified_files),
            )
            capture_exception(Exception(f"Found {len(modified_files)} modified delta files during first sync"))
            return

    if not new_file_uris:
        logger.debug("No new files to make queryable", batch_index=export_signal.batch_index)
        return

    logger.debug(
        "partial_data_loading",
        batch_index=export_signal.batch_index,
        new_file_count=len(new_file_uris),
        cumulative_row_count=export_signal.cumulative_row_count,
    )

    queryable_folder = await prepare_s3_files_for_querying(
        folder_path=job.folder_path(),
        table_name=export_signal.resource_name,
        file_uris=new_file_uris,
        delete_existing=(export_signal.batch_index == 0),
        use_timestamped_folders=False,
        logger=logger,
    )

    await validate_schema_and_update_table(
        run_id=str(job.id),
        team_id=job.team_id,
        schema_id=schema.id,
        table_schema_dict=internal_schema.to_hogql_types(),
        row_count=export_signal.cumulative_row_count,
        queryable_folder=queryable_folder,
        table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
        primary_keys=export_signal.primary_keys,
    )

    logger.debug(
        "partial_data_loading_complete",
        batch_index=export_signal.batch_index,
        queryable_folder=queryable_folder,
    )


def _file_count_after_write(
    delta_table: deltalake.DeltaTable, delta_table_ref: DeltaTableRef, deltalite_file_count_change: int | None
) -> int | None:
    """The table's file count after the write, from memory, or None when the handle cannot give it.

    A handle at the newest known version has the count. A handle one commit behind is behind by the
    deltalite commit of this write, whose added and removed files give the difference. Any other
    distance means a commit this process did not make, so the caller must read the log.
    """
    try:
        commits_behind = delta_table_ref.latest_known_version(delta_table) - delta_table.version()
    except Exception:
        return None
    if commits_behind == 0:
        return len(delta_table.file_uris())
    if commits_behind == 1 and isinstance(deltalite_file_count_change, int):
        return len(delta_table.file_uris()) + deltalite_file_count_change
    return None


def _run_post_load_for_already_processed_batch(export_signal: ExportSignalMessage) -> PostLoadResult:
    """Run post-load operations for a final batch whose data was already written to Delta Lake.

    Two deliveries land here: a redelivered final row whose earlier attempt committed the write
    but failed before post-load finished, and the final-only marker row an older producer inserts
    as a copy of the run's last data batch. Either way the data is in the table; only the post-load
    operations (compaction, S3 queryable folder prep, schema validation) are left.

    All async operations are run within a single async_to_sync call to avoid
    event loop lifecycle issues with aiohttp/s3fs clients.

    Returns the post-load result, with no queryable folder if post-load couldn't run.
    """

    async def _run() -> PostLoadResult:
        job = await ExternalDataJob.objects.prefetch_related("schema", "schema__source", "schema__table").aget(
            id=export_signal.job_id
        )
        schema = job.schema
        if schema is None:
            raise ValueError(f"ExternalDataJob {export_signal.job_id} has no schema")

        delta_table_ref = DeltaTableRef(
            resource_name=export_signal.resource_name,
            job=job,
            logger=logger,
        )

        delta_table = await delta_table_ref.get_delta_table()
        if delta_table is None:
            logger.error(
                "no_delta_table_for_post_load",
                external_data_job_id=export_signal.job_id,
                batch_index=export_signal.batch_index,
            )
            return PostLoadResult(queryable_folder=None)

        # The batch only decides which string columns hold JSON, and the first non-null value of a
        # column decides that. The rows are already in the table, so they are not read again.
        internal_schema = HogQLSchema()
        internal_schema.add_pyarrow_schema(pyarrow_schema_from_arrow_exportable(delta_table.schema()))
        internal_schema.add_pyarrow_table(read_parquet_first_values(export_signal.s3_path))
        table_schema_dict = internal_schema.to_hogql_types()

        post_load_result = await run_post_load_operations(
            job=job,
            schema=schema,
            source=schema.source,
            delta_table_ref=delta_table_ref,
            row_count=export_signal.total_rows or 0,
            table_schema_dict=table_schema_dict,
            resource_name=export_signal.resource_name,
            logger=logger,
            cdc_write_mode=export_signal.cdc_write_mode,
        )

        logger.debug("post_load_operations_complete_for_already_processed_batch")
        return post_load_result

    return async_to_sync(_run)()


def _release_pipeline_lock_for_job(export_signal: ExportSignalMessage) -> None:
    try:
        job = ExternalDataJob.objects.only("workflow_run_id").get(
            id=export_signal.job_id, team_id=export_signal.team_id
        )
        if job.workflow_run_id:
            release_v3_pipeline_lock(
                team_id=export_signal.team_id,
                schema_id=export_signal.schema_id,
                token=job.workflow_run_id,
            )
    except Exception as e:
        logger.error(
            "failed_to_release_v3_pipeline_lock",
            job_id=export_signal.job_id,
            schema_id=export_signal.schema_id,
            exc_info=True,
        )
        capture_exception(e)


def _mark_job_completed(export_signal: ExportSignalMessage) -> None:
    # Reconnect stale connections before the transaction; close_old_connections must never
    # run inside an atomic block since it can drop the connection mid-transaction.
    close_old_connections()

    # The Completed write and cursor promotion share one transaction so they commit together:
    # if promotion raises, the completion rolls back and the batch retries, never stranding a
    # terminal job with a stale cursor that a later append sync would re-extract past.
    with transaction.atomic():
        model = update_external_job_status(
            job_id=export_signal.job_id,
            team_id=export_signal.team_id,
            status=ExternalDataJob.Status.COMPLETED,
            logger=logger,
            latest_error=None,
        )

        job_completed = model.status == ExternalDataJob.Status.COMPLETED
        if job_completed:
            # Promote only when the Completed write landed: if the job was cancelled (absorbing
            # Failed) after the final batch passed should_process_batch, the staged incremental
            # cursor must not advance past data that was never fully loaded.
            _promote_staged_cursor(export_signal)

    if job_completed:
        async_to_sync(finish_row_tracking)(export_signal.team_id, export_signal.schema_id)

        logger.info(
            "job_marked_completed",
            external_data_job_id=export_signal.job_id,
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
        )
    else:
        logger.info(
            "job_completion_suppressed_terminal_status",
            external_data_job_id=export_signal.job_id,
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            status=model.status,
        )

    _release_pipeline_lock_for_job(export_signal)


# tonic's timeout layer cancels a call that outruns the client's per-request RPC deadline and
# surfaces it as status CANCELLED with the message "Timeout expired" — the client-side analog of
# DEADLINE_EXCEEDED above — and a connection closed mid-request as CANCELLED with "operation was
# canceled". Match the phrase rather than the whole status so a genuine cancellation still
# surfaces. Same phrases the data-imports source client (sources/temporalio/temporalio.py) and the
# Temporal schedule helpers (posthog/temporal/common/schedule.py) treat as transient.
_RETRYABLE_RPC_MESSAGES_BY_STATUS: dict[RPCStatusCode, tuple[str, ...]] = {
    RPCStatusCode.CANCELLED: ("Timeout expired", "operation was canceled"),
}


def _is_retryable_temporal_rpc_error(exc: BaseException) -> bool:
    # These fire-and-forget starts run outside a Temporal workflow, so unlike
    # `workflow.start_child_workflow` they get none of the server-side retry a durable
    # workflow command would have — a bare client RPC timeout would otherwise drop the
    # trigger permanently.
    if isinstance(exc, RPCError):
        if exc.status in (RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE):
            return True
        if any(phrase in exc.message for phrase in _RETRYABLE_RPC_MESSAGES_BY_STATUS.get(exc.status, ())):
            return True

    # `async_connect()` runs before any service client exists, so a transient failure to
    # reach the Temporal frontend (DNS blip, connection refused/reset) surfaces as the Rust
    # bridge's untyped RuntimeError rather than an RPCError — treat it the same way.
    return isinstance(exc, RuntimeError) and str(exc).startswith("Failed client connect:")


def _trigger_ducklake_register_data_imports(export_signal: ExportSignalMessage, prepared_queryable_folder: str) -> None:
    """Fire-and-forget start of `ducklake-register.data-imports` after a V3 final batch lands.

    V2 triggers this as a child workflow after `import_data_activity_sync`, but V3's
    `external-data-job` ends at extraction — the prepared Parquet generation only exists
    once this consumer's post-load operations prepare it, so the trigger lives here
    instead. The child starts only when this consumer's `*_load` deployment has Temporal
    client env vars configured; without them the trigger is skipped (load still succeeds).
    """
    if export_signal.cdc_write_mode == "scd2_append" or export_signal.sync_type == "cdc":
        # CDC finals land once per flush tick, so registering each one would copy a full
        # prepared generation into DuckLake continuously. An `incremental_merge` tick does
        # advance schema.table, so this leaves CDC schemas out of per-generation
        # registration entirely — a deliberate gap until that cadence is worked out.
        # scd2_append writes go to the _cdc companion, which the registration's staleness
        # check discards anyway.
        return

    try:
        from posthog.temporal.common.client import async_connect

        from products.managed_warehouse.backend.facade.temporal import (
            DuckLakeRegisterDataImportsInputs,
            DuckLakeRegisterDataImportsWorkflow,
            build_register_data_imports_workflow_id,
        )

        # Connect and start inside one event loop: sync_connect() builds the client in
        # asgiref's loop, and the start would then run on the loop async_to_sync spins up
        # here. Start is fire-and-forget — we only need the start ack, not the result.
        @retry(
            retry=retry_if_exception(_is_retryable_temporal_rpc_error),
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=5),
            reraise=True,
        )
        async def _start() -> None:
            temporal = await async_connect()
            await temporal.start_workflow(
                DuckLakeRegisterDataImportsWorkflow.run,
                DuckLakeRegisterDataImportsInputs(
                    team_id=export_signal.team_id,
                    job_id=export_signal.job_id,
                    schema_id=uuid.UUID(export_signal.schema_id),
                    prepared_queryable_folder=prepared_queryable_folder,
                ),
                id=build_register_data_imports_workflow_id(
                    team_id=export_signal.team_id,
                    schema_id=export_signal.schema_id,
                ),
                task_queue=settings.DUCKLAKE_TASK_QUEUE,
            )

        async_to_sync(_start)()
        logger.info(
            "ducklake_registration_workflow_started",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
        )
    except WorkflowAlreadyStartedError:
        # The id is one per schema, so a collision means a register is already
        # in flight. The next import after that run finishes can start.
        logger.info(
            "ducklake_registration_workflow_already_started",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
        )
    except Exception as e:
        logger.error(
            "failed_to_start_ducklake_registration_workflow",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
            exc_info=True,
        )
        capture_exception(e)


def _trigger_post_import_workflow(export_signal: ExportSignalMessage, table_size_written: bool = False) -> None:
    """Fire-and-forget start of `data-import-post-import` after a V3 final batch lands.

    V2 starts the same workflow from `external-data-job` after the COMPLETED status
    write, but on V3 that workflow ends at extraction — the loaded table only exists
    once this consumer's post-load operations and job completion finish, so the trigger
    lives here instead. Same tolerance as `_trigger_ducklake_register_data_imports`: the
    start only happens when this `*_load` deployment has Temporal client env vars
    configured; any failure is logged and captured without failing the load.
    """
    if export_signal.cdc_write_mode == "scd2_append" or export_signal.sync_type == "cdc":
        # CDC finals land once per flush tick; running the post-import fan-out on every
        # tick would spam these steps continuously. This also mirrors the pre-existing
        # workflow behavior: CDC streaming schemas return early from `external-data-job`
        # with skip_post_import_activities, so these steps never ran per tick there
        # either. Deliberate gap, same as the DuckLake registration trigger above.
        return

    try:
        from posthog.temporal.common.client import async_connect

        from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
            PostImportWorkflow,
            PostImportWorkflowInputs,
            build_post_import_workflow_id,
        )

        # Connect and start inside one event loop (see the DuckLake trigger above).
        # ALLOW_DUPLICATE_FAILED_ONLY keyed by job id: a redelivered final batch can't
        # double-run a completed post-import, but can retry a failed one.
        @retry(
            retry=retry_if_exception(_is_retryable_temporal_rpc_error),
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=1, max=5),
            reraise=True,
        )
        async def _start() -> None:
            temporal = await async_connect()
            await temporal.start_workflow(
                PostImportWorkflow.run,
                PostImportWorkflowInputs(
                    team_id=export_signal.team_id,
                    job_id=export_signal.job_id,
                    schema_id=export_signal.schema_id,
                    source_id=export_signal.source_id,
                    table_size_written=table_size_written,
                ),
                id=build_post_import_workflow_id(export_signal.job_id),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
            )

        async_to_sync(_start)()
        logger.info(
            "post_import_workflow_started",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "post_import_workflow_already_started",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
        )
    except Exception as e:
        logger.error(
            "failed_to_start_post_import_workflow",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            external_data_job_id=export_signal.job_id,
            exc_info=True,
        )
        capture_exception(e)


def _promote_staged_cursor(export_signal: ExportSignalMessage) -> None:
    # Runs inside the completion transaction; failures roll it back so the batch retries.
    schema = ExternalDataSchema.objects.get(id=export_signal.schema_id, team_id=export_signal.team_id)

    def merge_source_cursors(current: Any, candidate: Any) -> dict[str, Any]:
        source = SourceRegistry.get_source(ExternalDataSourceType(schema.source.source_type))
        return merge_cursor_payloads(source, current, candidate, logger)

    promoted = schema.promote_staged_incremental_values(
        export_signal.run_uuid, merge_source_cursors=merge_source_cursors
    )
    if promoted:
        logger.info(
            "staged_cursor_promoted",
            run_uuid=export_signal.run_uuid,
            team_id=export_signal.team_id,
            external_data_job_id=export_signal.job_id,
            external_data_schema_id=export_signal.schema_id,
        )
    elif schema.should_use_incremental_field:
        # The watermark stays where it was, so the next run re-reads this run's window. A source with
        # no watermark at all re-reads its full history.
        logger.warning(
            "staged_cursor_missing",
            run_uuid=export_signal.run_uuid,
            team_id=export_signal.team_id,
            external_data_job_id=export_signal.job_id,
            external_data_schema_id=export_signal.schema_id,
        )


def _mark_job_failed(export_signal: ExportSignalMessage, error: Exception) -> None:
    # Short-circuit if the job is already FAILED: redelivered DLQ'd messages
    # (the retry state stays in Redis until its 72h TTL) would otherwise spam
    # status updates and latest_error rewrites for a terminal job.
    existing = ExternalDataJob.objects.filter(
        id=export_signal.job_id, team_id=export_signal.team_id, status=ExternalDataJob.Status.FAILED
    ).first()
    if existing is not None:
        logger.info(
            "job_already_marked_failed",
            external_data_job_id=export_signal.job_id,
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
        )
        return

    update_external_job_status(
        job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        status=ExternalDataJob.Status.FAILED,
        logger=logger,
        latest_error=str(error),
    )

    logger.info(
        "job_marked_failed",
        external_data_job_id=export_signal.job_id,
        team_id=export_signal.team_id,
        external_data_schema_id=export_signal.schema_id,
        error=str(error),
    )

    _release_pipeline_lock_for_job(export_signal)


def _post_load_rss_sampler() -> RssPeakSampler | None:
    try:
        return get_governor().rss_sampler
    except Exception:
        logger.debug("post_load_rss_sampler_unavailable", exc_info=True)
        return None


def _record_post_load_phases(run_signal: ExportSignalMessage) -> AbstractContextManager[Any]:
    return record_post_load_phases(
        logger,
        _post_load_rss_sampler(),
        team_id=run_signal.team_id,
        external_data_schema_id=run_signal.schema_id,
        external_data_job_id=run_signal.job_id,
        source_id=run_signal.source_id,
        resource_name=run_signal.resource_name,
        run_uuid=run_signal.run_uuid,
        batch_index=run_signal.batch_index,
        sync_type=run_signal.sync_type,
    )


def _complete_run(run_signal: ExportSignalMessage, post_load_result: PostLoadResult) -> None:
    """Mark the job completed, then start the DuckLake registration and post-import workflows."""
    report_phase("finalize")
    with post_load_phase("job_completion"):
        _mark_job_completed(run_signal)

    if post_load_result.queryable_folder:
        with post_load_phase("ducklake_trigger"):
            _trigger_ducklake_register_data_imports(run_signal, post_load_result.queryable_folder)

    with post_load_phase("post_import_trigger"):
        _trigger_post_import_workflow(run_signal, post_load_result.table_size_written)


def _load_job(job_id: str) -> ExternalDataJob:
    return ExternalDataJob.objects.prefetch_related("schema", "schema__source", "schema__table").get(id=job_id)


def _finalize_run(
    run_signal: ExportSignalMessage,
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table_ref: DeltaTableRef,
    internal_schema: HogQLSchema,
    verify_ownership: Callable[[], None] | None,
) -> None:
    """Complete one run whose final batch is in the table: post-load, job status, cursor, triggers."""
    logger.info(
        "final_batch_received",
        external_data_job_id=run_signal.job_id,
        run_uuid=run_signal.run_uuid,
        batch_index=run_signal.batch_index,
        total_batches=run_signal.total_batches,
        total_rows=run_signal.total_rows,
        cdc_write_mode=run_signal.cdc_write_mode,
        cdc_table_mode=run_signal.cdc_table_mode,
        sync_type=run_signal.sync_type,
        schema_sync_type=schema.sync_type,
        schema_cdc_table_mode=schema.cdc_table_mode,
        resource_name=run_signal.resource_name,
    )

    # Minutes may have passed since the write — re-check before post-load commits and job
    # completion promote the staged cursor under a new owner.
    if verify_ownership is not None:
        verify_ownership()

    with _record_post_load_phases(run_signal):
        report_phase("post_load")
        post_load_result = async_to_sync(run_post_load_operations)(
            job=job,
            schema=schema,
            source=schema.source,
            delta_table_ref=delta_table_ref,
            row_count=run_signal.total_rows or 0,
            table_schema_dict=internal_schema.to_hogql_types(),
            resource_name=run_signal.resource_name,
            logger=logger,
            cdc_write_mode=run_signal.cdc_write_mode,
        )

        # Post-load can run minutes (compaction, S3 prep) — re-check before
        # completion promotes the cursor and releases the lock under a new owner.
        if verify_ownership is not None:
            verify_ownership()

        _complete_run(run_signal, post_load_result)

    logger.debug("post_load_operations_complete", external_data_job_id=run_signal.job_id)

    posthoganalytics.capture(
        distinct_id=get_machine_id(),
        event="warehouse_v3_load_completed",
        properties={
            "team_id": run_signal.team_id,
            "schema_id": run_signal.schema_id,
            "source_id": run_signal.source_id,
            "resource_name": run_signal.resource_name,
            "sync_type": run_signal.sync_type,
            "total_batches": run_signal.total_batches,
            "total_rows": run_signal.total_rows,
        },
    )


def process_message(
    message: Any,
    progress_callback: Callable[[], None] | None = None,
    verify_ownership: Callable[[], None] | None = None,
    attempt: int = 1,
) -> None:
    """Load one batch into Delta Lake. ``verify_ownership`` raises if the group lease was lost;
    re-checked before each lasting side effect since the heartbeat only detects loss between beats.

    ``attempt`` is this batch's delivery number, counting from 1. It selects how hard the
    idempotency check works: only a redelivery can have a half-finished predecessor to detect.
    """
    export_signal = ExportSignalMessage.from_dict(message)

    # The consumer is where v3 merges — the memory-heavy phase — actually run, so it must self-report
    # like the import activity does. Its own span key: extract (activity) and load (here) run
    # concurrently for the same job and must not clobber each other's reports.
    with workload_reporting(
        team_id=export_signal.team_id,
        schema_id=str(export_signal.schema_id),
        run_id=f"{export_signal.job_id}:load",
        host=socket.gethostname(),
        initial_phase="load",
    ):
        _process_message_reported(message, export_signal, progress_callback, verify_ownership, attempt)


def combine_export_signals(signals: list[ExportSignalMessage]) -> ExportSignalMessage:
    """The message one write of several consecutive batches stands for.

    It starts where the first batch starts, so batch 0 keeps its overwrite and its partial-loading
    semantics, and it ends how the last batch ends, so a final batch in the set completes the run.
    When the set spans runs the message carries the first run's identity; each run's own completion
    comes from `final_run_signals`.
    """
    head, tail = signals[0], signals[-1]
    return dataclasses.replace(
        head,
        row_count=sum(signal.row_count for signal in signals),
        byte_size=sum(signal.byte_size for signal in signals),
        is_final_batch=tail.is_final_batch,
        total_batches=tail.total_batches,
        total_rows=tail.total_rows,
        data_folder=tail.data_folder or head.data_folder,
        schema_path=tail.schema_path or head.schema_path,
        cumulative_row_count=tail.cumulative_row_count,
    )


def final_run_signals(constituents: list[ExportSignalMessage]) -> list[ExportSignalMessage]:
    """One combined message per run whose last member of the set is its final batch, in load order.

    Each run completes on its own: its post-load, its job status and its cursor promotion happen
    in the order the runs were loaded, which is the order the loader would have completed them
    one batch at a time.
    """
    members = [CoalesceMember.from_signal(signal) for signal in constituents]
    finals: list[ExportSignalMessage] = []
    for run_uuid in runs_in_order(members):
        run_signals = [signal for signal in constituents if signal.run_uuid == run_uuid]
        if run_signals[-1].is_final_batch:
            finals.append(combine_export_signals(run_signals))
    return finals


def process_messages(
    messages: list[Any],
    progress_callback: Callable[[], None] | None = None,
    verify_ownership: Callable[[], None] | None = None,
    attempt: int = 1,
) -> None:
    """Load consecutive batches of one run, or of consecutive runs, into Delta Lake as one write.

    Raises ``CoalescingDeclined`` before any side effect when the set cannot be loaded as one
    (a constituent already landed, or the batches' schemas do not concatenate); the engine then
    loads the constituents one by one.
    """
    signals = [ExportSignalMessage.from_dict(message) for message in messages]
    violation = set_violation([CoalesceMember.from_signal(signal) for signal in signals])
    if violation is not None:
        raise CoalescingDeclined(violation)
    combined = combine_export_signals(signals)

    with workload_reporting(
        team_id=combined.team_id,
        schema_id=str(combined.schema_id),
        run_id=f"{combined.job_id}:load",
        host=socket.gethostname(),
        initial_phase="load",
    ):
        _process_message_reported(
            messages[0], combined, progress_callback, verify_ownership, attempt, constituents=signals
        )


def _process_external_destinations_only(
    export_signal: "ExportSignalMessage",
    verify_ownership: Callable[[], None] | None,
) -> None:
    """Deliver a batch for a run that writes to external destinations only.

    Same lifecycle as any other run, minus everything Delta-specific. The batch is done when
    every destination has taken it, and the final batch completes the job.
    """

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.delivery import (  # noqa: PLC0415
        deliver_batch_to_destinations,
    )

    report_phase("deliver")
    deliver_batch_to_destinations(export_signal)

    if not export_signal.is_final_batch:
        return

    # Minutes may have passed, so re-check ownership before completion promotes the cursor.
    if verify_ownership is not None:
        verify_ownership()

    report_phase("finalize")
    _mark_job_completed(export_signal)


def _read_constituents(constituents: list[ExportSignalMessage]) -> pa.Table:
    """Read every constituent's parquet file and concatenate them in load order.

    Batches of one run were converged onto one accumulated schema when they were staged, so they
    normally concatenate as they are; a later batch, or a later run, can still carry a column an
    earlier one lacked, which permissive promotion fills with nulls. Anything that still does not
    fit declines the set, since nothing has been written yet.

    The order matters: the writer keeps the last row per key, so a later run's row for a key an
    earlier run also carried is the one that lands.
    """
    tables = [read_parquet(signal.s3_path) for signal in constituents]
    try:
        return pa.concat_tables(tables, promote_options="permissive")
    except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as e:
        raise CoalescingDeclined(f"batch schemas do not concatenate: {e}") from e


def _process_message_reported(
    message: Any,
    export_signal: "ExportSignalMessage",
    progress_callback: Callable[[], None] | None,
    verify_ownership: Callable[[], None] | None,
    attempt: int = 1,
    constituents: list[ExportSignalMessage] | None = None,
) -> None:
    # The (run, batch index) pairs this write stands for: one for an ordinary batch, every member for a set.
    members = (
        [(signal.run_uuid, signal.batch_index) for signal in constituents]
        if constituents is not None
        else [(export_signal.run_uuid, export_signal.batch_index)]
    )

    # Reconnect stale app-DB connections up front so the ORM queries below don't burn all batch attempts.
    close_old_connections()

    timer = BatchStepTimer()
    # Taken before any step that can raise, so a batch that fails leaves no handle for its retry.
    retained_table = GROUP_TABLE_HANDLES.take(export_signal, attempt=attempt)

    # Imported here, not at module scope: `load/__init__` imports this module, and delivery
    # imports `load.idempotency`, so a module-level import closes the cycle.
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.delivery import (  # noqa: PLC0415
        deliver_batch_to_destinations,
        warehouse_is_a_destination,
    )

    try:
        # Build the helper early so the idempotency check can use it as a
        # delta-history fallback when the Redis dedup flag is missing — the case
        # where the writer crashed between `DeltaWriter.write` committing and
        # `mark_batch_as_processed` being called.
        with timer.step("job_load"):
            job = _load_job(export_signal.job_id)
        schema = job.schema
        if schema is None:
            raise ValueError(f"ExternalDataJob {export_signal.job_id} has no schema")

        delta_table_ref = DeltaTableRef(
            resource_name=export_signal.resource_name,
            job=job,
            logger=logger,
            is_first_sync=export_signal.is_first_ever_sync,
            # Batch 0 of a first sync writes the table, so only that batch expects to find none.
            expect_missing=export_signal.is_first_ever_sync and export_signal.batch_index == 0,
        )

        if not warehouse_is_a_destination(export_signal):
            # The customer asked for their data elsewhere and not here, so there is no delta
            # write, no table to register and no post-import to run.
            _process_external_destinations_only(export_signal, verify_ownership)
            return

        with timer.step("idempotency_check"):
            if constituents is not None:
                # A set is all-or-nothing: a member that already landed means the others must be checked
                # and written one at a time, which the single-batch path knows how to do.
                for run_uuid, index in members:
                    if is_batch_already_processed(
                        export_signal.team_id,
                        export_signal.schema_id,
                        run_uuid,
                        index,
                        delta_table_ref=delta_table_ref,
                        is_first_attempt=attempt <= 1,
                    ):
                        raise CoalescingDeclined(f"batch {index} of run {run_uuid} was already processed")
                already_processed = False
            else:
                already_processed = is_batch_already_processed(
                    export_signal.team_id,
                    export_signal.schema_id,
                    export_signal.run_uuid,
                    export_signal.batch_index,
                    delta_table_ref=delta_table_ref,
                    is_first_attempt=attempt <= 1,
                )

        # The warehouse having this batch says nothing about the other destinations, so
        # delivery runs on every path and decides for itself what is left to do. Gating it on
        # the warehouse's marker would strand a destination that failed, and gating publication
        # on the write marker would leave a full refresh staged and never swapped in.
        report_phase("deliver")
        with timer.step("deliver"):
            deliver_batch_to_destinations(export_signal)

        if already_processed and not export_signal.is_final_batch:
            IDEMPOTENCY_HIT_TOTAL.inc()
            logger.info(
                "batch_already_processed",
                team_id=export_signal.team_id,
                external_data_schema_id=export_signal.schema_id,
                run_uuid=export_signal.run_uuid,
                batch_index=export_signal.batch_index,
            )
            return

        if already_processed and export_signal.is_final_batch:
            logger.info(
                "batch_already_processed_running_post_load",
                team_id=export_signal.team_id,
                external_data_schema_id=export_signal.schema_id,
                run_uuid=export_signal.run_uuid,
                batch_index=export_signal.batch_index,
            )
            if verify_ownership is not None:
                verify_ownership()
            with _record_post_load_phases(export_signal):
                report_phase("post_load")
                post_load_result = _run_post_load_for_already_processed_batch(export_signal)
                # Post-load can run minutes (compaction, S3 prep) — re-check before
                # completion promotes the cursor and releases the lock under a new owner.
                if verify_ownership is not None:
                    verify_ownership()
                _complete_run(export_signal, post_load_result)
            return

        logger.debug(
            "message_received",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            resource_name=export_signal.resource_name,
            batch_index=export_signal.batch_index,
            is_final_batch=export_signal.is_final_batch,
            row_count=export_signal.row_count,
            s3_path=export_signal.s3_path,
            sync_type=export_signal.sync_type,
        )

        primary_keys = export_signal.primary_keys
        cdc_write_mode = export_signal.cdc_write_mode

        report_phase("read")
        with timer.step("parquet_read"), PARQUET_READ_DURATION_SECONDS.time():
            if constituents is not None:
                pa_table = _read_constituents(constituents)
            else:
                pa_table = read_parquet(export_signal.s3_path)

        logger.debug(
            "parquet_file_read",
            batch_index=export_signal.batch_index,
            s3_path=export_signal.s3_path,
            num_rows=pa_table.num_rows,
            num_columns=pa_table.num_columns,
            column_names=pa_table.column_names,
        )

        table_handle_reused = False
        if retained_table is not None and cdc_write_mode is None:
            with timer.step("table_refresh"):
                table_handle_reused = async_to_sync(delta_table_ref.adopt_open_table)(retained_table)
        retained_table = None
        if table_handle_reused:
            existing_delta_table = async_to_sync(delta_table_ref.get_delta_table)()
        else:
            with timer.step("table_open"):
                existing_delta_table = async_to_sync(delta_table_ref.get_delta_table)()

        with timer.step("partition"):
            pa_table = _apply_partitioning(export_signal, pa_table, existing_delta_table, schema)

        # Capture file URIs before write for partial data loading. The listing is O(files in
        # table), so skip it entirely when no consumer wants it — during a long first sync the
        # table can hold millions of files and every batch would pay to build a list nothing reads.
        previous_file_uris = (
            existing_delta_table.file_uris()
            if existing_delta_table is not None and _partial_data_loading_applies(export_signal, schema)
            else []
        )

        deltalite_file_count_change: int | None = None

        # Tag every delta commit with (run_uuid, batch_index) so that a redelivery after a writer
        # crash can detect "already committed" even when the Redis dedup flag is missing. A set
        # names every member, so each one's redelivery finds the commit. See `is_batch_already_processed`.
        commit_metadata = {
            "run_uuid": export_signal.run_uuid,
            "batch_index": str(export_signal.batch_index),
        }
        if constituents is not None:
            commit_metadata["batch_indexes"] = ",".join(
                str(index) for run_uuid, index in members if run_uuid == export_signal.run_uuid
            )
            if any(run_uuid != export_signal.run_uuid for run_uuid, _ in members):
                commit_metadata["members"] = commit_members_tag(members)

        resolution_enabled = cdc_write_mode is not None

        with timer.step("cdc_resolve"):
            pa_table = _enrich_cdc_rows(
                pa_table,
                primary_keys=primary_keys,
                cdc_write_mode=cdc_write_mode,
                existing_delta_table=existing_delta_table,
                batch_index=export_signal.batch_index,
                verify_deletes=resolution_enabled,
            )

            if resolution_enabled:
                pa_table = _resolve_cdc_positions(
                    pa_table,
                    primary_keys=primary_keys or [],
                    cdc_write_mode=cdc_write_mode,
                )

        if existing_delta_table is not None:
            with timer.step("schema_evolve"):
                try:
                    pa_table = evolve_pyarrow_schema(
                        pa_table,
                        existing_delta_table.schema(),
                        merge_key_columns=[*(primary_keys or []), *(export_signal.partition_keys or [])],
                    )
                except SchemaColumnTypeChangedException as e:
                    # A safe numeric widening is mechanically recoverable: stamp reset_pipeline so the
                    # next scheduled sync resets and re-syncs the table, and reword the failure so
                    # latest_error stops telling the customer to reset manually. Unsafe transitions
                    # (and everything with the flag off) re-raise unchanged.
                    amended_message = maybe_schedule_auto_widen_resync(schema=schema, job=job, error=e)
                    if amended_message is not None:
                        e.args = (amended_message,)
                    raise

        if verify_ownership is not None:
            with timer.step("ownership_check"):
                verify_ownership()

        # The writer narrows this to `merge` for an upsert; an append stays `write` to its commit.
        report_phase("write")
        if cdc_write_mode == "scd2_append":
            logger.debug(
                "writing_scd2_to_delta_lake",
                primary_keys=primary_keys,
                batch_index=export_signal.batch_index,
            )

            with (
                timer.step("write"),
                DELTA_WRITE_DURATION_SECONDS.labels(write_type="scd2_append").time(),
            ):
                scd2_writer = Scd2DeltaWriter(
                    delta_table_ref,
                    valid_from_column=SCD2_VALID_FROM_COLUMN,
                    valid_to_column=SCD2_VALID_TO_COLUMN,
                )
                delta_table = async_to_sync(scd2_writer.write)(
                    data=pa_table,
                    primary_keys=primary_keys or [],
                    commit_metadata=commit_metadata,
                )
        else:
            write_type = _get_write_type(export_signal.sync_type)

            # First batch should overwrite the table, but only if not resuming
            should_overwrite_table = export_signal.batch_index == 0 and not export_signal.is_resume

            logger.debug(
                "writing_to_delta_lake",
                write_type=write_type,
                should_overwrite_table=should_overwrite_table,
                primary_keys=primary_keys,
                batch_index=export_signal.batch_index,
            )

            with (
                timer.step("write"),
                DELTA_WRITE_DURATION_SECONDS.labels(write_type=write_type).time(),
            ):
                delta_writer = DeltaWriter(delta_table_ref)
                delta_table = async_to_sync(delta_writer.write)(
                    data=pa_table,
                    write_type=write_type,
                    should_overwrite_table=should_overwrite_table,
                    primary_keys=primary_keys,
                    progress_callback=progress_callback,
                    commit_metadata=commit_metadata,
                )
                deltalite_file_count_change = delta_writer.deltalite_file_count_change

        DELTA_ROWS_WRITTEN_TOTAL.inc(pa_table.num_rows)

        # Marked as soon as the commit lands, before post-load: the final row of a run carries its own
        # data now, so a post-load failure must send the retry down the post-load-only path rather
        # than through the write again.
        with timer.step("mark_processed"):
            for run_uuid, index in members:
                mark_batch_as_processed(export_signal.team_id, export_signal.schema_id, run_uuid, index)

        # file_count is the signal that shows a table fragmenting during a long load, so it stays —
        # but listing every file costs O(files in table), which is the very thing it measures. Sample
        # it instead: the trend is what matters, and the version is cheap enough to log every batch.
        sample_file_count = export_signal.batch_index % FILE_COUNT_LOG_SAMPLE_EVERY == 0
        file_count = (
            _file_count_after_write(delta_table, delta_table_ref, deltalite_file_count_change)
            if sample_file_count
            else None
        )

        # The handle `write` returns can be one deltalite commit behind the log. Column names and
        # types cannot differ across that commit, so the schema below reads it as is; a file list
        # can, so the readers of one go through the ref, which catches the handle up first. The
        # sampled count needs that read only when the commit's own numbers cannot give it: batch 0
        # is a sample, so the read would otherwise cost each run a log listing.
        with timer.step("post_write"):
            if (sample_file_count and file_count is None) or _partial_data_loading_applies(export_signal, schema):
                current_delta_table = async_to_sync(delta_table_ref.get_delta_table)()
                if current_delta_table is not None:
                    delta_table = current_delta_table
                if sample_file_count and file_count is None:
                    file_count = len(delta_table.file_uris())

            internal_schema = HogQLSchema()
            # Build from the Delta table schema first to cover all columns from
            # all batches, then overlay the current batch for JSON detection.
            internal_schema.add_pyarrow_schema(pyarrow_schema_from_arrow_exportable(delta_table.schema()))
            internal_schema.add_pyarrow_table(pa_table)

        logger.debug(
            "batch_written_to_delta_lake",
            team_id=export_signal.team_id,
            external_data_schema_id=export_signal.schema_id,
            batch_index=export_signal.batch_index,
            rows_written=pa_table.num_rows,
            batch_count=len(members),
            delta_version=delta_table_ref.latest_known_version(delta_table),
            file_count=file_count,
            table_handle="reused" if table_handle_reused else "opened",
            **timer.log_fields(),
        )

        async_to_sync(_handle_partial_data_loading)(
            export_signal=export_signal,
            job=job,
            schema=schema,
            delta_table=delta_table,
            previous_file_uris=previous_file_uris,
            internal_schema=internal_schema,
        )

        # Post-load compaction owns a full governor slot. Drop the input batch before entering it so
        # Arrow's buffers do not remain resident alongside the compaction working set.
        del pa_table

        # Every run whose final batch landed in this write completes now, in load order.
        if constituents is not None:
            finals = final_run_signals(constituents)
        else:
            finals = [export_signal] if export_signal.is_final_batch else []
        for run_signal in finals:
            run_job = job if run_signal.job_id == export_signal.job_id else _load_job(run_signal.job_id)
            run_schema = run_job.schema
            if run_schema is None:
                raise ValueError(f"ExternalDataJob {run_signal.job_id} has no schema")
            _finalize_run(
                run_signal,
                job=run_job,
                schema=run_schema,
                delta_table_ref=delta_table_ref,
                internal_schema=internal_schema,
                verify_ownership=verify_ownership,
            )

        # A run that completed here ran its post-load maintenance, and the next run can reset the
        # table, so only a write that stays inside one unfinished run hands its handle on.
        if not finals and cdc_write_mode is None and all(run_uuid == export_signal.run_uuid for run_uuid, _ in members):
            open_table = delta_table_ref.pop_cached_table()
            if open_table is not None:
                GROUP_TABLE_HANDLES.retain(
                    export_signal, open_table, last_batch_index=max(index for _, index in members)
                )
    except OwnershipLostError:
        # Benign fencing abandon: the engine re-raises this without writing a
        # failure status, so it must not count as a load failure in analytics either.
        raise
    except Exception as e:
        posthoganalytics.capture(
            distinct_id=get_machine_id(),
            event="warehouse_v3_load_failed",
            properties={
                "team_id": export_signal.team_id,
                "schema_id": export_signal.schema_id,
                "source_id": export_signal.source_id,
                "resource_name": export_signal.resource_name,
                "sync_type": export_signal.sync_type,
                "batch_index": export_signal.batch_index,
                "error_type": type(e).__name__,
                "error_message": str(e)[:1000],
            },
        )
        raise
