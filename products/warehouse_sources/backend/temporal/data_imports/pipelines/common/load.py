import json
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
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.metrics import POST_LOAD_DURATION_SECONDS
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import normalize_column_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.post_load_phases import (
    note_post_load_phase,
    post_load_phase,
    recorded_phase,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    sync_engineering_analytics_views,
    sync_revenue_analytics_views,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
    own_linked_table,
    set_initial_sync_complete,
)
from products.warehouse_sources.backend.temporal.data_imports.query_folder_state import QueryFolderPointerHistory
from products.warehouse_sources.backend.temporal.data_imports.util import prepare_s3_files_for_querying
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
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


_UNRESOLVED = object()


def _get_json_path_value(raw_value: Any, path: list[str]) -> Any:
    """Walk a JSON string's object members; distinguish a missing member from null."""
    if raw_value is None:
        return _UNRESOLVED  # a null root does not establish that the nested member exists

    try:
        value = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return _UNRESOLVED  # not JSON -> path unresolvable

    for part in path:
        if value is None:
            return _UNRESOLVED  # null intermediate parent; the leaf was never observed
        if not isinstance(value, dict) or part not in value:
            return _UNRESOLVED  # structurally missing -> unresolvable
        value = value[part]

    if isinstance(value, (dict, list)):
        return _UNRESOLVED  # leaf must be scalar
    return value


def parse_member_path(path: str) -> list[str] | None:
    """Parse a simple dotted member path, optionally prefixed with '$.'.

    Supported: "meta.updated_at", "$.meta.updated_at", "updated_at"
    Not supported: array indexes, wildcards, filters, or quoted JSONPath keys.
    Only member access is accepted because a cursor must resolve to at most one
    scalar per record.
    """
    path = path.strip()

    if path.startswith("$."):
        path = path[2:]
    elif path.startswith("$"):
        return None

    if not path:
        return None

    parts = path.split(".")
    if any(not part or part != part.strip() or any(char in part for char in "$[]*?'\"") for part in parts):
        return None

    return parts


def resolve_incremental_values(table: pa.Table, field_name: str) -> list | None:
    """Return row-aligned raw cursor values, or None if the field cannot be resolved.

    For parsed dotted paths, only the top-level column name is normalized; nested
    JSON keys retain their source spelling. Nested paths can resolve from JSON-string
    columns. If at least one row resolves, unresolved rows are None; otherwise the
    normalized flat-column lookup is tried, including for paths rejected by the parser
    and for a batch whose nested root is entirely null.
    """

    parts = parse_member_path(field_name)
    empty_nested_root = False

    if parts is not None:
        root_name = normalize_column_name(parts[0])
        if root_name in table.column_names:
            root_column = table[root_name]
            # Nested struct/list columns may already be JSON strings here, serialized upstream by
            # evolve_pyarrow_schema; resolve dotted paths from that representation.
            if len(parts) > 1 and (pa.types.is_string(root_column.type) or pa.types.is_large_string(root_column.type)):
                root_values = root_column.to_pylist()
                if not root_values or all(value is None for value in root_values):
                    # Nothing observed through the nested path this batch, but the normalized flat
                    # column may still carry the field; defer before leaving the cursor alone.
                    empty_nested_root = True
                else:
                    values = [_get_json_path_value(v, parts[1:]) for v in root_values]
                    if any(v is not _UNRESOLVED for v in values):
                        return [None if v is _UNRESOLVED else v for v in values]

    # Fallback: a real top-level column. Covers single-segment paths, pre-flattened
    # keys such as "meta_updated_at", and (compatibility) names that are not valid
    # member paths but still normalize onto a real flat column.
    flat_name = normalize_column_name(".".join(parts) if parts is not None else field_name)
    if flat_name and flat_name in table.column_names:
        column = table[flat_name]
        if not pa.types.is_nested(column.type):
            return column.to_pylist()

    if empty_nested_root:
        return []  # nothing observed anywhere -> leave the cursor alone
    return None


def get_incremental_field_value(
    schema: ExternalDataSchema | None,
    table: pa.Table,
    aggregate: Literal["max"] | Literal["min"] = "max",
) -> Any:
    # CDC and xmin schemas track their own cursor (CDC log position, xmin ceiling) outside of
    # sync_type_config["incremental_field"] — that key can be a stale leftover from a prior
    # incremental config and must not be looked up for these sync types.
    if schema is None or not schema.should_use_incremental_field:
        return None

    incremental_field_name: str | None = schema.sync_type_config.get("incremental_field")
    if incremental_field_name is None:
        return None

    if aggregate not in ("max", "min"):
        raise Exception(f"Unsupported aggregate function for get_incremental_field_value: {aggregate}")

    raw_values = resolve_incremental_values(table, incremental_field_name)
    if raw_values is None:
        raise IncrementalFieldMissingFromDataError(incremental_field_name, table)

    processed_values = [
        process_incremental_value(value, schema.incremental_field_type) for value in raw_values if value is not None
    ]
    if not processed_values:
        # Empty batch, or every row null: leave the cursor where it is.
        return None

    processed_column = pa.array(processed_values)

    if aggregate == "max":
        last_value = pc.max(processed_column)
    else:
        last_value = pc.min(processed_column)

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

        await database_sync_to_async_pool(retry_on_operational_error(_check_and_notify))()
    except Exception as e:
        # Silently fail, we don't want this to crash the pipeline
        # Sending an email is not critical to the pipeline
        await logger.aexception(f"Error notifying revenue analytics that sync has completed: {e}")
        capture_exception(e)


async def _seed_cdc_companion_from_snapshot(
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    source: "ExternalDataSource",
    snapshot_delta_table_ref: "DeltaTableRef",
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
        companion_resource_name as build_companion_resource_name,
    )
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.hogql_schema import HogQLSchema

    snapshot_dt = await snapshot_delta_table_ref.get_delta_table()
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

    companion_resource_name = build_companion_resource_name(schema.name)
    companion_ref = DeltaTableRef(
        resource_name=companion_resource_name,
        job=job,
        logger=logger,
    )

    # Reset so a full resync always starts the companion fresh.
    await companion_ref.reset_table()

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
        await DeltaWriter(companion_ref).write(
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
        delta_table_ref=companion_ref,
        row_count=total_rows,
        table_schema_dict=hogql_schema.to_hogql_types(),
        resource_name=companion_resource_name,
        logger=logger,
        cdc_write_mode="scd2_append",
    )


@recorded_phase("delta_maintenance")
async def _run_delta_maintenance(
    schema: ExternalDataSchema,
    delta_table_ref: "DeltaTableRef",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.maintenance import (  # noqa: PLC0415 — keeps the heavy deltalake dep off this module's top-level import path
        DeltaMaintenance,
    )

    # Threshold maintenance for every sync type: most final batches leave the table with nothing
    # to compact, and an unconditional compact still lists and plans every file. Vacuum when the
    # commit or time cadence is due, then compact when compaction can remove files; see
    # DeltaMaintenance.run_scheduled. A non-CDC sync also compacts once its small merge files add up
    # (see compact_if_fragmented).
    logger.debug("Running threshold-based delta maintenance")
    with POST_LOAD_DURATION_SECONDS.labels(operation="maintenance").time():
        await DeltaMaintenance(delta_table_ref).run_scheduled(
            schema,
            is_cdc_companion=is_cdc_companion,
            compact_small_files=not schema.is_cdc,
        )


def _stored_sync_type_config(schema_id: Any, team_id: int) -> Any:
    """Read the schema's `sync_type_config` as committed rather than from the in-memory schema: the
    query folder pointer record was written by whichever run flipped the pointer, which a long-lived
    schema object may predate."""
    return (
        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id)
        .values_list("sync_type_config", flat=True)
        .first()
    )


@recorded_phase("publish")
async def _publish_queryable_files(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table_ref: "DeltaTableRef",
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

        def _own_queryable_folder() -> str | None:
            table = own_linked_table(schema, job.pipeline)
            return table.queryable_folder if table is not None else None

        existing_queryable_folder = await database_sync_to_async_pool(_own_queryable_folder)()

    sync_type_config = await database_sync_to_async_pool(_stored_sync_type_config)(schema.id, job.team_id)
    pointer_history = QueryFolderPointerHistory.from_config(
        sync_type_config, f"{NamingConvention.normalize_identifier(resource_name)}__query"
    )

    # File URIs are listed after delta maintenance so the queryable folder serves the compacted
    # layout rather than the pre-compaction small files.
    with post_load_phase("list_live_files"):
        file_uris = await delta_table_ref.get_file_uris()
        note_post_load_phase(live_files=len(file_uris))
    logger.debug(f"Preparing S3 files - total parquet files: {len(file_uris)}")
    with POST_LOAD_DURATION_SECONDS.labels(operation="prepare_s3").time():
        folder = await prepare_s3_files_for_querying(
            await database_sync_to_async_pool(job.folder_path)(),
            resource_name,
            file_uris,
            delete_existing=True,
            existing_queryable_folder=existing_queryable_folder,
            logger=logger,
            refresh_file_uris=delta_table_ref.get_file_uris,
            double_buffer=True,
            pointer_history=pointer_history,
        )
    return folder


@recorded_phase("sync_bookkeeping")
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
        await set_initial_sync_complete(schema_id=schema.id, team_id=job.team_id, logger=logger)

    if resource is not None:
        await finalize_desc_sort_incremental_value(resource, schema, last_incremental_field_value, logger)


@recorded_phase("register_table")
async def _register_table(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    delta_table_ref: "DeltaTableRef",
    row_count: int,
    table_schema_dict: dict[str, str],
    resource: "Optional[SourceResponse]",
    queryable_folder: str,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import (
        validate_schema_and_update_table,
    )

    # The handle is already open from the maintenance step, so the schema comes from the in-memory
    # snapshot rather than from another log read.
    delta_table = await delta_table_ref.get_delta_table()
    delta_schema_json = delta_table.schema().to_json() if delta_table is not None else None
    # Only a table whose run count is not its size reads the count. The handle is the one the publish
    # step listed, so the count matches the files the query folder now holds.
    live_row_count = (
        await delta_table_ref.get_live_row_count() if schema.table_row_count_is_cumulative or row_count == 0 else None
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
            delta_schema_json=delta_schema_json,
            live_row_count=live_row_count,
        )
    logger.debug("Finished validating schema and updating table")


@recorded_phase("cdc_post_load")
async def _run_cdc_post_load(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_ref: "DeltaTableRef",
    row_count: int,
    table_schema_dict: dict[str, str],
    resource_name: str,
    queryable_folder: str,
    cdc_write_mode: Optional[str],
    is_cdc_companion: bool,
    is_initial_load: bool,
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
                live_row_count=await delta_table_ref.get_live_row_count(),
            )
        logger.debug("Finished registering CDC companion table")
        return

    # After the initial snapshot load for a CDC schema, seed the companion _cdc table
    # with the snapshot rows as synthetic INSERT events. Seeding resets the companion, so
    # it must happen only on the initial load: a missing cdc_write_mode alone does not mean
    # "initial" — a redelivered final batch reaches post-load without one, and re-seeding
    # there throws away every SCD2 version the stream has accumulated since.
    should_seed = is_initial_load and cdc_write_mode is None and schema.cdc_table_mode in ("cdc_only", "both")
    logger.info(
        "cdc_seed_check",
        should_seed=should_seed,
        cdc_write_mode=cdc_write_mode,
        is_initial_load=is_initial_load,
        sync_type=schema.sync_type,
        cdc_table_mode=schema.cdc_table_mode,
    )
    if should_seed:
        logger.info("Seeding CDC companion table from snapshot")
        await _seed_cdc_companion_from_snapshot(
            schema=schema,
            job=job,
            source=source,
            snapshot_delta_table_ref=delta_table_ref,
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
        delta_table_ref: "DeltaTableRef",
        is_cdc_companion: bool,
        logger: FilteringBoundLogger,
    ) -> None: ...


async def _notify_revenue_analytics_step(
    *,
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_ref: "DeltaTableRef",
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
    delta_table_ref: "DeltaTableRef",
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
    delta_table_ref: "DeltaTableRef",
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
    delta_table_ref: "DeltaTableRef",
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

    delta_table = await delta_table_ref.get_delta_table()
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


def _post_load_step_phase_name(step: PostLoadStep) -> str:
    name = getattr(step, "__name__", type(step).__name__)
    return name.strip("_").removesuffix("_step")


async def _run_post_load_steps(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_ref: "DeltaTableRef",
    is_cdc_companion: bool,
    logger: FilteringBoundLogger,
) -> None:
    for step in POST_LOAD_STEPS:
        with post_load_phase(_post_load_step_phase_name(step)):
            await step(
                job=job,
                schema=schema,
                source=source,
                delta_table_ref=delta_table_ref,
                is_cdc_companion=is_cdc_companion,
                logger=logger,
            )


async def run_post_load_operations(
    job: ExternalDataJob,
    schema: ExternalDataSchema,
    source: "ExternalDataSource",
    delta_table_ref: "Optional[DeltaTableRef]",
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
        1. Delta maintenance (compact when fragmented, otherwise vacuum on commit cadence)
        2. Prepare S3 files for querying
        3. Sync bookkeeping (last_synced_at, initial_sync_complete, desc-sort incremental finalization)
        4. Register the table (skipped for CDC companion writes and cdc_only initial loads)
        5. CDC post-load (companion registration or snapshot seeding), for CDC schemas only
        6. POST_LOAD_STEPS: product side effects (revenue notification, revenue/engineering
           analytics views, repartition detection)

    Returns the queryable folder the table now serves from, or None when there is no delta table.
    """
    if delta_table_ref is None or await delta_table_ref.get_delta_table() is None:
        # A clean run that wrote zero rows creates no delta table, so there is nothing to publish or
        # register. Finalize the sync bookkeeping anyway: without it last_synced_at and
        # initial_sync_complete never advance, leaving the schema stuck "completed but not
        # initial-synced" on every subsequent run.
        logger.debug("No deltalake table; finalizing bookkeeping for a zero-row run")
        await _finalize_sync_bookkeeping(job, schema, resource, last_incremental_field_value, logger)
        return None

    # Detect CDC companion writes — scd2_append writes always go to the companion _cdc resource.
    # In this case we must NOT touch schema.table (the snapshot table) and must register the companion
    # table independently, otherwise we overwrite the snapshot queryable_folder with the SCD2 path.
    is_cdc_companion = cdc_write_mode == "scd2_append"
    is_cdc_schema = schema.sync_type == ExternalDataSchema.SyncType.CDC
    # Read before the bookkeeping below sets the flag, which would otherwise make every run
    # look like a continuation.
    is_initial_load = not schema.initial_sync_complete

    await _run_delta_maintenance(schema, delta_table_ref, is_cdc_companion, logger)

    queryable_folder = await _publish_queryable_files(
        job, schema, delta_table_ref, resource_name, is_cdc_companion, logger
    )

    await _finalize_sync_bookkeeping(job, schema, resource, last_incremental_field_value, logger)

    # For cdc_only mode during the initial load, skip registering the consolidated
    # DataWarehouseTable — only the _cdc companion table should be visible.
    # The DeltaLake files still exist on S3 for the seeding step to read from.
    is_cdc_only_initial = cdc_write_mode is None and is_cdc_schema and schema.cdc_table_mode == "cdc_only"

    if not is_cdc_companion and not is_cdc_only_initial:
        await _register_table(
            job, schema, delta_table_ref, row_count, table_schema_dict, resource, queryable_folder, logger
        )

    if is_cdc_companion or is_cdc_schema:
        await _run_cdc_post_load(
            job=job,
            schema=schema,
            source=source,
            delta_table_ref=delta_table_ref,
            row_count=row_count,
            table_schema_dict=table_schema_dict,
            resource_name=resource_name,
            queryable_folder=queryable_folder,
            cdc_write_mode=cdc_write_mode,
            is_cdc_companion=is_cdc_companion,
            is_initial_load=is_initial_load,
            logger=logger,
        )

    await _run_post_load_steps(job, schema, source, delta_table_ref, is_cdc_companion, logger)

    return queryable_folder
