import uuid
import socket
from collections.abc import Callable
from typing import Any, Literal

from django.conf import settings
from django.db import close_old_connections, transaction

import s3fs
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
    batch_max_seq,
    has_engine_seq,
    is_cdc_write_resolution_enabled,
    persist_load_position,
    read_load_position,
    resolve_batch,
    verify_delete_enrichment,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import (
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
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.scd2 import Scd2DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    validate_schema_and_update_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    OwnershipLostError,
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
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import (
    ExportSignalMessage,
    SyncTypeLiteral,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import read_parquet
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    release_v3_pipeline_lock,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import finish_row_tracking
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying
from products.warehouse_sources.backend.temporal.data_imports.workload_report import workload_reporting

logger = structlog.get_logger(__name__)


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
    team_id: str = "",
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
                        CDC_DELETE_ENRICHMENT_VIOLATIONS_TOTAL.labels(team_id=team_id).inc(
                            report.rows_with_nulled_columns
                        )
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
    sync_type_config: dict | None,
    resource_name: str,
    primary_keys: list[str],
    cdc_write_mode: str | None,
    team_id: str,
) -> tuple[pa.Table, int | None]:
    """Drop rows this lane's table has already applied.

    Returns the batch and the position to record, which the caller persists only once the write
    commits — a position ahead of the table would skip rows that never landed.
    """
    if not has_engine_seq(pa_table):
        return pa_table, None

    watermark = read_load_position(sync_type_config, resource_name)

    pa_table, stats = resolve_batch(
        pa_table,
        primary_keys,
        watermark=watermark,
        cdc_write_mode=cdc_write_mode,
    )
    for reason, dropped in (("superseded", stats.superseded), ("duplicate_key", stats.duplicate_key)):
        if dropped:
            CDC_SEQ_GUARD_ROWS_DROPPED_TOTAL.labels(team_id=team_id, reason=reason).inc(dropped)

    return pa_table, batch_max_seq(pa_table)


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


async def _handle_partial_data_loading(
    export_signal: ExportSignalMessage,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table: deltalake.DeltaTable,
    previous_file_uris: list[str],
    internal_schema: HogQLSchema,
) -> None:
    """Make data available for querying during first-ever sync for Stripe sources."""
    if not export_signal.is_first_ever_sync:
        return

    if not supports_partial_data_loading(schema):
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


def _run_post_load_for_already_processed_batch(export_signal: ExportSignalMessage) -> str | None:
    """Run post-load operations for a final batch whose data was already written to Delta Lake.

    The batch data (S3 read, partitioning, Delta Lake write) was already handled when
    the batch was first processed with is_final_batch=False. We only need to run
    post-load operations (compaction, S3 queryable folder prep, schema validation).

    All async operations are run within a single async_to_sync call to avoid
    event loop lifecycle issues with aiohttp/s3fs clients.

    Returns the prepared queryable_folder, or None if post-load couldn't run.
    """
    # Clear cached S3FileSystem instances to avoid reusing sessions bound to a
    # previously closed event loop (async_to_sync creates/destroys loops).
    s3fs.S3FileSystem.clear_instance_cache()

    async def _run() -> str | None:
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
            return None

        pa_table = read_parquet(export_signal.s3_path)
        internal_schema = HogQLSchema()
        internal_schema.add_pyarrow_schema(pyarrow_schema_from_arrow_exportable(delta_table.schema()))
        internal_schema.add_pyarrow_table(pa_table)
        table_schema_dict = internal_schema.to_hogql_types()

        prepared_queryable_folder = await run_post_load_operations(
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
        return prepared_queryable_folder

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


def _is_retryable_temporal_rpc_error(exc: BaseException) -> bool:
    # These fire-and-forget starts run outside a Temporal workflow, so unlike
    # `workflow.start_child_workflow` they get none of the server-side retry a durable
    # workflow command would have — a bare client RPC timeout would otherwise drop the
    # trigger permanently.
    return isinstance(exc, RPCError) and exc.status in (RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE)


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


def _trigger_post_import_workflow(export_signal: ExportSignalMessage) -> None:
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
    promoted = schema.promote_staged_incremental_values(export_signal.run_uuid)
    if promoted:
        logger.info(
            "staged_cursor_promoted",
            run_uuid=export_signal.run_uuid,
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


def process_message(
    message: Any,
    progress_callback: Callable[[], None] | None = None,
    verify_ownership: Callable[[], None] | None = None,
) -> None:
    """Load one batch into Delta Lake. ``verify_ownership`` raises if the group lease was lost;
    re-checked before each lasting side effect since the heartbeat only detects loss between beats."""
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
        _process_message_reported(message, export_signal, progress_callback, verify_ownership)


def _process_message_reported(
    message: Any,
    export_signal: "ExportSignalMessage",
    progress_callback: Callable[[], None] | None,
    verify_ownership: Callable[[], None] | None,
) -> None:
    # Reconnect stale app-DB connections up front so the ORM queries below don't burn all batch attempts.
    close_old_connections()

    # Clear cached S3FileSystem instances to avoid reusing sessions bound to a
    # previously closed event loop (async_to_sync creates/destroys loops).
    s3fs.S3FileSystem.clear_instance_cache()

    try:
        team_id_str = str(export_signal.team_id)
        schema_id_str = str(export_signal.schema_id)

        # Build the helper early so the idempotency check can use it as a
        # delta-history fallback when the Redis dedup flag is missing — the case
        # where the writer crashed between `DeltaWriter.write` committing and
        # `mark_batch_as_processed` being called.
        job = ExternalDataJob.objects.prefetch_related("schema", "schema__source", "schema__table").get(
            id=export_signal.job_id
        )
        schema = job.schema
        if schema is None:
            raise ValueError(f"ExternalDataJob {export_signal.job_id} has no schema")

        delta_table_ref = DeltaTableRef(
            resource_name=export_signal.resource_name,
            job=job,
            logger=logger,
            is_first_sync=export_signal.is_first_ever_sync,
        )

        already_processed = is_batch_already_processed(
            export_signal.team_id,
            export_signal.schema_id,
            export_signal.run_uuid,
            export_signal.batch_index,
            delta_table_ref=delta_table_ref,
        )

        if already_processed and not export_signal.is_final_batch:
            IDEMPOTENCY_HIT_TOTAL.labels(team_id=team_id_str, schema_id=schema_id_str).inc()
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
            prepared_queryable_folder = _run_post_load_for_already_processed_batch(export_signal)
            # Post-load can run minutes (compaction, S3 prep) — re-check before
            # completion promotes the cursor and releases the lock under a new owner.
            if verify_ownership is not None:
                verify_ownership()
            _mark_job_completed(export_signal)
            if prepared_queryable_folder:
                _trigger_ducklake_register_data_imports(export_signal, prepared_queryable_folder)
            _trigger_post_import_workflow(export_signal)
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

        with PARQUET_READ_DURATION_SECONDS.time():
            pa_table = read_parquet(export_signal.s3_path)

        logger.debug(
            "parquet_file_read",
            batch_index=export_signal.batch_index,
            s3_path=export_signal.s3_path,
            num_rows=pa_table.num_rows,
            num_columns=pa_table.num_columns,
            column_names=pa_table.column_names,
        )

        existing_delta_table = async_to_sync(delta_table_ref.get_delta_table)()

        pa_table = _apply_partitioning(export_signal, pa_table, existing_delta_table, schema)

        # Capture file URIs before write for partial data loading
        previous_file_uris = existing_delta_table.file_uris() if existing_delta_table else []

        primary_keys = export_signal.primary_keys
        cdc_write_mode = export_signal.cdc_write_mode

        # Tag every delta commit with (run_uuid, batch_index) so that a Kafka
        # redelivery after a writer crash can detect "already committed" even when
        # the Redis dedup flag is missing. See `is_batch_already_processed`.
        commit_metadata = {
            "run_uuid": export_signal.run_uuid,
            "batch_index": str(export_signal.batch_index),
        }

        resolution_enabled = cdc_write_mode is not None and is_cdc_write_resolution_enabled(
            export_signal.team_id, schema_id_str, export_signal.run_uuid
        )

        pa_table = _enrich_cdc_rows(
            pa_table,
            primary_keys=primary_keys,
            cdc_write_mode=cdc_write_mode,
            existing_delta_table=existing_delta_table,
            batch_index=export_signal.batch_index,
            verify_deletes=resolution_enabled,
            team_id=team_id_str,
        )

        pending_load_position: int | None = None
        if resolution_enabled:
            pa_table, pending_load_position = _resolve_cdc_positions(
                pa_table,
                sync_type_config=schema.sync_type_config,
                resource_name=export_signal.resource_name,
                primary_keys=primary_keys or [],
                cdc_write_mode=cdc_write_mode,
                team_id=team_id_str,
            )

        if existing_delta_table is not None:
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
            verify_ownership()

        if cdc_write_mode == "scd2_append":
            logger.debug(
                "writing_scd2_to_delta_lake",
                primary_keys=primary_keys,
                batch_index=export_signal.batch_index,
            )

            with DELTA_WRITE_DURATION_SECONDS.labels(
                team_id=team_id_str, schema_id=schema_id_str, write_type="scd2_append"
            ).time():
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

            with DELTA_WRITE_DURATION_SECONDS.labels(
                team_id=team_id_str, schema_id=schema_id_str, write_type=write_type
            ).time():
                delta_table = async_to_sync(DeltaWriter(delta_table_ref).write)(
                    data=pa_table,
                    write_type=write_type,
                    should_overwrite_table=should_overwrite_table,
                    primary_keys=primary_keys,
                    progress_callback=progress_callback,
                    commit_metadata=commit_metadata,
                )

        DELTA_ROWS_WRITTEN_TOTAL.labels(team_id=team_id_str, schema_id=schema_id_str).inc(pa_table.num_rows)

        if pending_load_position is not None:
            # Best-effort: failing here would fail a batch that is already written, and the cost of
            # losing the position is re-applying rows next time, which is a no-op.
            try:
                persist_load_position(
                    schema.id, export_signal.team_id, export_signal.resource_name, pending_load_position
                )
            except Exception:  # noqa: BLE001 - bookkeeping must never fail a committed write
                logger.warning("cdc_load_position_persist_failed", exc_info=True)

        internal_schema = HogQLSchema()
        # Build from the Delta table schema first to cover all columns from
        # all batches, then overlay the current batch for JSON detection.
        internal_schema.add_pyarrow_schema(pyarrow_schema_from_arrow_exportable(delta_table.schema()))
        internal_schema.add_pyarrow_table(pa_table)

        logger.debug(
            "batch_written_to_delta_lake",
            batch_index=export_signal.batch_index,
            file_count=len(delta_table.file_uris()),
        )

        async_to_sync(_handle_partial_data_loading)(
            export_signal=export_signal,
            job=job,
            schema=schema,
            delta_table=delta_table,
            previous_file_uris=previous_file_uris,
            internal_schema=internal_schema,
        )

        if export_signal.is_final_batch:
            logger.info(
                "final_batch_received",
                batch_index=export_signal.batch_index,
                total_batches=export_signal.total_batches,
                total_rows=export_signal.total_rows,
                cdc_write_mode=export_signal.cdc_write_mode,
                cdc_table_mode=export_signal.cdc_table_mode,
                sync_type=export_signal.sync_type,
                schema_sync_type=schema.sync_type,
                schema_cdc_table_mode=schema.cdc_table_mode,
                resource_name=export_signal.resource_name,
            )

            # Minutes may have passed since the batch's write — re-check before post-load
            # commits and job completion promote the staged cursor under a new owner.
            if verify_ownership is not None:
                verify_ownership()

            prepared_queryable_folder = async_to_sync(run_post_load_operations)(
                job=job,
                schema=schema,
                source=schema.source,
                delta_table_ref=delta_table_ref,
                row_count=export_signal.total_rows or 0,
                table_schema_dict=internal_schema.to_hogql_types(),
                resource_name=export_signal.resource_name,
                logger=logger,
                cdc_write_mode=export_signal.cdc_write_mode,
            )

            # Post-load can run minutes (compaction, S3 prep) — re-check before
            # completion promotes the cursor and releases the lock under a new owner.
            if verify_ownership is not None:
                verify_ownership()

            _mark_job_completed(export_signal)

            if prepared_queryable_folder:
                _trigger_ducklake_register_data_imports(export_signal, prepared_queryable_folder)

            _trigger_post_import_workflow(export_signal)

            logger.debug("post_load_operations_complete")

        mark_batch_as_processed(
            export_signal.team_id, export_signal.schema_id, export_signal.run_uuid, export_signal.batch_index
        )

        if export_signal.is_final_batch:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="warehouse_v3_load_completed",
                properties={
                    "team_id": export_signal.team_id,
                    "schema_id": export_signal.schema_id,
                    "source_id": export_signal.source_id,
                    "resource_name": export_signal.resource_name,
                    "sync_type": export_signal.sync_type,
                    "total_batches": export_signal.total_batches,
                    "total_rows": export_signal.total_rows,
                },
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
