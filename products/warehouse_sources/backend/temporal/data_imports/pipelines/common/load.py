from typing import TYPE_CHECKING, Any, Literal, Optional, Protocol

from django.db.models import F

import pyarrow as pa
import pyarrow.compute as pc
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, process_incremental_value
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.metrics import POST_LOAD_DURATION_SECONDS
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    sync_engineering_analytics_views,
    sync_revenue_analytics_views,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import set_initial_sync_complete
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import (
        DeltaTableHelper,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

LOGGER = get_logger(__name__)


async def update_job_row_count(job_id: str, count: int, logger: FilteringBoundLogger) -> None:
    await logger.adebug(f"Updating rows_synced with +{count}")
    await database_sync_to_async_pool(
        retry_on_operational_error(
            lambda: ExternalDataJob.objects.filter(id=job_id).update(rows_synced=F("rows_synced") + count)
        )
    )()


class IncrementalFieldMissingFromDataError(Exception):
    """The configured incremental field isn't a column in the extracted rows.

    A config error (e.g. a display label like "created_at" persisted instead of the real field
    "created", or a field the endpoint simply doesn't return) — retrying can never fix it, so the
    message is registered in ``Any_Source_Errors`` to pause the schema with user guidance instead
    of failing every scheduled sync with a raw pyarrow KeyError.
    """

    def __init__(self, field_name: str, table: pa.Table) -> None:
        super().__init__(
            f'Incremental field "{field_name}" was not found in the data returned by the source. '
            f"Edit the table's sync method and pick a valid incremental field. "
            f"Available columns: {', '.join(sorted(table.column_names)[:50])}"
        )


def get_incremental_field_value(
    schema: ExternalDataSchema | None, table: pa.Table, aggregate: Literal["max"] | Literal["min"] = "max"
) -> Any:
    # CDC and xmin schemas track their own cursor (CDC log position, xmin ceiling) outside of
    # sync_type_config["incremental_field"] — that key can be a stale leftover from a prior
    # incremental config and must not be looked up for these sync types.
    if schema is None or not schema.should_use_incremental_field:
        return None

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return None

    normalized_field_name = normalize_column_name(incremental_field_name)
    if normalized_field_name not in table.column_names:
        raise IncrementalFieldMissingFromDataError(incremental_field_name, table)

    column = table[normalized_field_name]
    processed_column = pa.array(
        [process_incremental_value(val, schema.incremental_field_type) for val in column.to_pylist()]
    )

    if aggregate == "max":
        last_value = pc.max(processed_column)
    elif aggregate == "min":
        last_value = pc.min(processed_column)
    else:
        raise Exception(f"Unsupported aggregate function for get_incremental_field_value: {aggregate}")

    return last_value.as_py()


def supports_partial_data_loading(schema: ExternalDataSchema) -> bool:
    """
    We should be able to roll this out to all source types in the future.
    Currently only Stripe sources support partial data loading.
    """
    return schema.source.source_type == ExternalDataSourceType.STRIPE


async def notify_revenue_analytics_that_sync_has_completed(
    schema: ExternalDataSchema, source: "ExternalDataSource", logger: FilteringBoundLogger
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
        CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    )

    try:

        @database_sync_to_async_pool
        def _check_and_notify():
            if (
                schema.name == STRIPE_CHARGE_RESOURCE_NAME
                and source.source_type == ExternalDataSourceType.STRIPE
                and source.revenue_analytics_config.enabled
                and not schema.team.revenue_analytics_config.notified_first_sync
            ):
                # For every admin in the org, send a revenue analytics ready event
                # This will trigger a Campaign in PostHog and send an email
                for user in schema.team.all_users_with_access():
                    if user.distinct_id is not None:
                        posthoganalytics.capture(
                            distinct_id=user.distinct_id,
                            event="revenue_analytics_ready",
                            properties={"source_type": source.source_type},
                        )

                # Mark the team as notified, avoiding spamming emails
                schema.team.revenue_analytics_config.notified_first_sync = True
                schema.team.revenue_analytics_config.save()

        await _check_and_notify()
    except Exception as e:
        # Silently fail, we don't want this to crash the pipeline
        # Sending an email is not critical to the pipeline
        await logger.aexception(f"Error notifying revenue analytics that sync has completed: {e}")
        capture_exception(e)


async def _seed_cdc_companion_from_snapshot(
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    source: "ExternalDataSource",
    snapshot_delta_table_helper: "DeltaTableHelper",
    logger: FilteringBoundLogger,
) -> None:
    """Populate the _cdc companion table with snapshot rows as synthetic INSERT events.

    Called after the initial full-refresh snapshot completes for a CDC schema that uses
    'cdc_only' or 'both' mode.  Any existing companion table is reset first so that a
    full resync always starts the _cdc history fresh from the new snapshot.

    Reads the snapshot in batches via PyArrow dataset scanning to avoid loading the
    entire table into memory.
    """
    import asyncio

    from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
        CDC_OP_COLUMN,
        CDC_TIMESTAMP_COLUMN,
        DELETED_AT_COLUMN,
        DELETED_COLUMN,
        SCD2_VALID_FROM_COLUMN,
        SCD2_VALID_TO_COLUMN,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta_table_helper import (
        DeltaTableHelper,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema

    snapshot_dt = await snapshot_delta_table_helper.get_delta_table()
    if snapshot_dt is None:
        return

    dataset = await asyncio.to_thread(snapshot_dt.to_pyarrow_dataset)

    # Strip any pre-existing CDC metadata columns from the snapshot (defensive).
    cdc_meta_cols = {
        CDC_OP_COLUMN,
        CDC_TIMESTAMP_COLUMN,
        DELETED_COLUMN,
        DELETED_AT_COLUMN,
        SCD2_VALID_FROM_COLUMN,
        SCD2_VALID_TO_COLUMN,
    }
    read_columns = [c for c in dataset.schema.names if c not in cdc_meta_cols]

    companion_resource_name = f"{schema.name}_cdc"
    companion_helper = DeltaTableHelper(
        resource_name=companion_resource_name,
        job=job,
        logger=logger,
    )

    # Reset so a full resync always starts the companion fresh.
    await companion_helper.reset_table()

    hogql_schema = HogQLSchema()
    total_rows = 0

    SEED_BATCH_SIZE = 50_000
    reader = await asyncio.to_thread(
        lambda: dataset.scanner(columns=read_columns, batch_size=SEED_BATCH_SIZE).to_reader()
    )

    def _read_next_batch(r: pa.RecordBatchReader) -> pa.RecordBatch | None:
        try:
            return r.read_next_batch()
        except StopIteration:
            return None

    # Use Unix epoch (0) for the seed timestamp so that any real WAL commit timestamp
    # is guaranteed to be greater.  Without this, seeded rows end up with
    # valid_from > valid_to when the first CDC event has a commit time that predates
    # the snapshot ingestion time (e.g. changes captured during the initial snapshot load).
    ts_type = pa.timestamp("us", tz="UTC")
    epoch_us = 0

    while True:
        batch = await asyncio.to_thread(_read_next_batch, reader)
        if batch is None:
            break

        batch_table = pa.Table.from_batches([batch])
        if batch_table.num_rows == 0:
            continue

        n = batch_table.num_rows
        batch_table = (
            batch_table.append_column(pa.field(CDC_OP_COLUMN, pa.string()), pa.array(["I"] * n, type=pa.string()))
            .append_column(pa.field(CDC_TIMESTAMP_COLUMN, ts_type), pa.array([epoch_us] * n, type=ts_type))
            .append_column(pa.field(DELETED_COLUMN, pa.bool_()), pa.array([False] * n, type=pa.bool_()))
            .append_column(pa.field(DELETED_AT_COLUMN, ts_type), pa.array([None] * n, type=ts_type))
            .append_column(pa.field(SCD2_VALID_FROM_COLUMN, ts_type), pa.array([epoch_us] * n, type=ts_type))
            .append_column(pa.field(SCD2_VALID_TO_COLUMN, ts_type), pa.array([None] * n, type=ts_type))
        )

        # Plain append — the companion table is freshly reset so there are no existing
        # rows to close, making SCD2 merge unnecessary.
        await companion_helper.write_to_deltalake(
            data=batch_table,
            write_type="append",
            should_overwrite_table=False,
            primary_keys=None,
        )
        hogql_schema.add_pyarrow_table(batch_table)
        total_rows += n

    if total_rows == 0:
        return

    await run_post_load_operations(
        job=job,
        schema=schema,
        source=source,
        delta_table_helper=companion_helper,
        row_count=total_rows,
        table_schema_dict=hogql_schema.to_hogql_types(),
        resource_name=companion_resource_name,
        logger=logger,
        cdc_write_mode="scd2_append",
    )


async def _run_delta_maintenance(
    schema: ExternalDataSchema,
    delta_table_helper: "DeltaTableHelper",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
        is_transient_maintenance_error,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
        DeltaMaintenance,
    )

    maintenance = DeltaMaintenance(delta_table_helper)
    if schema.is_cdc:
        # CDC finals land once per tick per changed schema, so unconditional compaction would run
        # near-continuously after mostly-tiny merges. Use threshold/cadence maintenance instead:
        # compact when fragmented, otherwise vacuum once enough commits have accrued.
        logger.debug("Running threshold-based delta maintenance")
        with POST_LOAD_DURATION_SECONDS.labels(operation="maintenance").time():
            await maintenance.run_scheduled(schema, is_cdc_companion=is_cdc_companion)
    else:
        logger.debug("Triggering compaction and vacuuming on delta table")
        try:
            with POST_LOAD_DURATION_SECONDS.labels(operation="compact").time():
                await maintenance.compact_table()
        except Exception as e:
            if is_transient_maintenance_error(e):
                # A rate-limited or connectivity blip talking to our own S3 bucket (or a concurrent
                # maintenance pass losing a file race) isn't a bug - the next sync's maintenance pass
                # retries the same idempotent cleanup.
                logger.warning(f"Compaction skipped: transient infra error: {e}")
            else:
                capture_exception(e)
                logger.exception(f"Compaction failed: {e}", exc_info=e)


async def _publish_queryable_files(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table_helper: "DeltaTableHelper",
    resource_name: str,
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> str:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import build_table_name

    if is_cdc_companion:
        # Look up the existing companion table's queryable_folder (not the main schema.table).
        # build_table_name accesses job.pipeline (FK), so do it inside the sync wrapper.
        _resource_name = resource_name

        @database_sync_to_async_pool
        def _get_companion_queryable_folder():
            name = build_table_name(job.pipeline, _resource_name)
            return (
                DataWarehouseTable.objects.filter(
                    team_id=job.team_id,
                    name=name,
                    external_data_source_id=job.pipeline.id,
                    deleted=False,
                )
                .values_list("queryable_folder", flat=True)
                .first()
            )

        existing_queryable_folder = await _get_companion_queryable_folder()
    else:
        existing_queryable_folder = await database_sync_to_async_pool(
            lambda: schema.table.queryable_folder if schema.table else None
        )()

    # File URIs are listed after delta maintenance so the queryable folder serves the compacted
    # layout rather than the pre-compaction small files.
    file_uris = await delta_table_helper.get_file_uris()
    logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
    with POST_LOAD_DURATION_SECONDS.labels(operation="prepare_s3").time():
        return await prepare_s3_files_for_querying(
            await database_sync_to_async_pool(job.folder_path)(),
            resource_name,
            file_uris,
            delete_existing=True,
            existing_queryable_folder=existing_queryable_folder,
            logger=logger,
            refresh_file_uris=delta_table_helper.get_file_uris,
        )


async def _finalize_sync_bookkeeping(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    resource: "Optional[SourceResponse]",
    last_incremental_field_value: Any,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
        finalize_desc_sort_incremental_value,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import update_last_synced_at

    logger.debug("Updating last synced at timestamp on schema")
    await update_last_synced_at(job_id=str(job.id), schema_id=str(schema.id), team_id=job.team_id)

    if not schema.initial_sync_complete:
        await logger.adebug("Setting initial_sync_complete on schema")
        await set_initial_sync_complete(schema_id=schema.id, team_id=job.team_id)

    if resource is not None:
        await finalize_desc_sort_incremental_value(resource, schema, last_incremental_field_value, logger)


async def _register_table(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    row_count: int,
    table_schema_dict: dict[str, str],
    resource: "Optional[SourceResponse]",
    queryable_folder: str,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
        validate_schema_and_update_table,
    )

    logger.debug("Validating schema and updating table")
    with POST_LOAD_DURATION_SECONDS.labels(operation="validate_schema").time():
        await validate_schema_and_update_table(
            run_id=str(job.id),
            team_id=job.team_id,
            schema_id=schema.id,
            table_schema_dict=table_schema_dict,
            row_count=row_count,
            queryable_folder=queryable_folder,
            table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            primary_keys=resource.primary_keys if resource is not None else None,
        )
    logger.debug("Finished validating schema and updating table")


async def _run_cdc_post_load(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "DeltaTableHelper",
    row_count: int,
    table_schema_dict: dict[str, str],
    resource_name: str,
    queryable_folder: str,
    cdc_write_mode: Optional[str],
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
        register_cdc_companion_table,
    )

    if is_cdc_companion:
        logger.debug("Registering CDC companion table")
        with POST_LOAD_DURATION_SECONDS.labels(operation="validate_schema").time():
            await register_cdc_companion_table(
                run_id=str(job.id),
                team_id=job.team_id,
                schema_id=schema.id,
                resource_name=resource_name,
                row_count=row_count,
                table_format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
                queryable_folder=queryable_folder,
                table_schema_dict=table_schema_dict,
                set_as_schema_table=schema.cdc_table_mode == "cdc_only",
            )
        logger.debug("Finished registering CDC companion table")
        return

    # After the initial snapshot load for a CDC schema, seed the companion _cdc table
    # with the snapshot rows as synthetic INSERT events.  Only fires when cdc_write_mode
    # is None (initial non-CDC load), NOT on every CDC consolidated streaming batch.
    should_seed = cdc_write_mode is None and schema.cdc_table_mode in ("cdc_only", "both")
    logger.info(
        "cdc_seed_check",
        should_seed=should_seed,
        cdc_write_mode=cdc_write_mode,
        sync_type=schema.sync_type,
        cdc_table_mode=schema.cdc_table_mode,
    )
    if should_seed:
        logger.info("Seeding CDC companion table from snapshot")
        await _seed_cdc_companion_from_snapshot(
            schema=schema,
            job=job,
            source=source,
            snapshot_delta_table_helper=delta_table_helper,
            logger=logger,
        )
        logger.info("Finished seeding CDC companion table from snapshot")


class PostLoadStep(Protocol):
    async def __call__(
        self,
        *,
        job: ExternalDataJob,
        schema: ExternalDataSchema,
        source: "ExternalDataSource",
        delta_table_helper: "DeltaTableHelper",
        is_cdc_companion: bool,
        logger: FilteringBoundLogger,
    ) -> None: ...


async def _notify_revenue_analytics_step(
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "DeltaTableHelper",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    logger.debug("Notifying revenue analytics that sync has completed")
    await notify_revenue_analytics_that_sync_has_completed(schema, source, logger)


async def _sync_revenue_analytics_views_step(
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "DeltaTableHelper",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    logger.debug("Syncing revenue analytics views if needed")
    await database_sync_to_async_pool(sync_revenue_analytics_views)(schema, source)


async def _sync_engineering_analytics_views_step(
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "DeltaTableHelper",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    logger.debug("Syncing engineering analytics views if needed")
    await database_sync_to_async_pool(sync_engineering_analytics_views)(schema, source)


async def _maybe_flag_repartition_step(
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "DeltaTableHelper",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    # Measure partition sizes and flag the table for an in-place repartition if a partition has grown
    # past the memory-safe budget. CDC tables are excluded for now (their companion-table semantics
    # need separate validation). Detection never raises — it must not break post-load.
    if is_cdc_companion or schema.sync_type == ExternalDataSchema.SyncType.CDC:
        return

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
        maybe_flag_for_repartition,
    )

    delta_table = await delta_table_helper.get_delta_table()
    if delta_table is not None:
        await maybe_flag_for_repartition(schema, source, job, delta_table, logger)


# Product-facing side effects outside the core publish/register flow. Entries share the PostLoadStep
# signature so other products can eventually register theirs here instead of editing this module
# (see external_product_hooks.py for the registry pattern).
POST_LOAD_STEPS: tuple[PostLoadStep, ...] = (
    _notify_revenue_analytics_step,
    _sync_revenue_analytics_views_step,
    _sync_engineering_analytics_views_step,
    _maybe_flag_repartition_step,
)


async def run_post_load_operations(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_helper: "Optional[DeltaTableHelper]",
    row_count: int,
    table_schema_dict: dict[str, str],
    resource_name: str,
    logger: FilteringBoundLogger,
    last_incremental_field_value: Any = None,
    resource: "Optional[SourceResponse]" = None,
    cdc_write_mode: Optional[str] = None,
) -> Optional[str]:
    """
    Orchestrator that runs all post-load operations, in order:
        1. Delta maintenance (threshold-based for CDC schemas, unconditional compaction otherwise)
        2. Prepare S3 files for querying
        3. Sync bookkeeping (last_synced_at, initial_sync_complete, desc-sort incremental finalization)
        4. Register the table (skipped for CDC companion writes and cdc_only initial loads)
        5. CDC post-load (companion registration or snapshot seeding), for CDC schemas only
        6. POST_LOAD_STEPS: product side effects (revenue notification, revenue/engineering
           analytics views, repartition detection)

    Returns the queryable folder the table now serves from, or None when there is no delta table.
    """
    if delta_table_helper is None or await delta_table_helper.get_delta_table() is None:
        logger.debug("No deltalake table, not continuing with post-run ops")
        return None

    # Detect CDC companion writes — scd2_append writes always go to the companion _cdc resource.
    # In this case we must NOT touch schema.table (the snapshot table) and must register the companion
    # table independently, otherwise we overwrite the snapshot queryable_folder with the SCD2 path.
    is_cdc_companion = cdc_write_mode == "scd2_append"
    is_cdc_schema = schema.sync_type == ExternalDataSchema.SyncType.CDC

    await _run_delta_maintenance(schema, delta_table_helper, is_cdc_companion, logger)

    queryable_folder = await _publish_queryable_files(
        job, schema, delta_table_helper, resource_name, is_cdc_companion, logger
    )

    await _finalize_sync_bookkeeping(job, schema, resource, last_incremental_field_value, logger)

    # For cdc_only mode during the initial load, skip registering the consolidated
    # DataWarehouseTable — only the _cdc companion table should be visible.
    # The DeltaLake files still exist on S3 for the seeding step to read from.
    is_cdc_only_initial = cdc_write_mode is None and is_cdc_schema and schema.cdc_table_mode == "cdc_only"

    if not is_cdc_companion and not is_cdc_only_initial:
        await _register_table(job, schema, row_count, table_schema_dict, resource, queryable_folder, logger)

    if is_cdc_companion or is_cdc_schema:
        await _run_cdc_post_load(
            job=job,
            schema=schema,
            source=source,
            delta_table_helper=delta_table_helper,
            row_count=row_count,
            table_schema_dict=table_schema_dict,
            resource_name=resource_name,
            queryable_folder=queryable_folder,
            cdc_write_mode=cdc_write_mode,
            is_cdc_companion=is_cdc_companion,
            logger=logger,
        )

    for step in POST_LOAD_STEPS:
        await step(
            job=job,
            schema=schema,
            source=source,
            delta_table_helper=delta_table_helper,
            is_cdc_companion=is_cdc_companion,
            logger=logger,
        )

    return queryable_folder
