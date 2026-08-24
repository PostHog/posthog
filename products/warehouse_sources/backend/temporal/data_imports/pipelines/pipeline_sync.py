import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from django.db import transaction
from django.db.models import Prefetch

import dlt
import pyarrow
import pendulum
import dlt.common
import dlt.extract
import dlt.common.libs
import dlt.common.libs.pyarrow
import dlt.extract.incremental
import dlt.extract.incremental.transform
from clickhouse_driver.errors import ServerException
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import retry_on_db_connection_drop

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    mark_initial_sync_complete,
)
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    filter_dwh_columns_by_enabled_columns,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


def merge_columns(
    db_columns: dict[str, str],
    table_schema_dict: dict[str, str],
    existing_columns: dict[str, Any],
) -> dict[str, Any]:
    """Build column metadata, preserving StringJSONDatabaseField from prior runs.

    Columns present in existing_columns but absent from db_columns are preserved
    to avoid losing schema information when get_columns() returns incomplete
    results during a sync (e.g., transient S3/ClickHouse introspection failures).
    """
    columns: dict[str, Any] = {}
    for column_name, db_column_type in db_columns.items():
        hogql_type = table_schema_dict.get(column_name)

        if hogql_type is None:
            capture_exception(Exception(f"HogQL type not found for column: {column_name}"))
            continue

        existing_column = existing_columns.get(column_name)
        existing_hogql_type = existing_column.get("hogql") if isinstance(existing_column, dict) else None
        if existing_hogql_type == "StringJSONDatabaseField" and hogql_type == "StringDatabaseField":
            hogql_type = "StringJSONDatabaseField"

        columns[column_name] = {
            "clickhouse": db_column_type,
            "hogql": hogql_type,
        }

    # Preserve columns from prior syncs that are missing from the current introspection.
    # This prevents column loss when get_columns() returns partial results mid-sync.
    for column_name, column_meta in existing_columns.items():
        if column_name in columns:
            continue

        if isinstance(column_meta, dict):
            columns[column_name] = column_meta
        elif isinstance(column_meta, str):
            columns[column_name] = {
                "clickhouse": column_meta,
                "hogql": table_schema_dict.get(column_name, "StringDatabaseField"),
            }

    return columns


def _from_arrow_scalar(arrow_value: pyarrow.Scalar) -> Any:
    """Converts arrow scalar into Python type. Currently adds "UTC" to naive date times and converts all others to UTC"""
    row_value = arrow_value.as_py()

    if isinstance(row_value, date) and not isinstance(row_value, datetime):
        return row_value
    elif isinstance(row_value, datetime):
        row_value = pendulum.instance(row_value).in_tz("UTC")
    return row_value


dlt.common.libs.pyarrow.from_arrow_scalar = _from_arrow_scalar  # ty: ignore[invalid-assignment]
dlt.extract.incremental.transform.from_arrow_scalar = _from_arrow_scalar  # ty: ignore[invalid-assignment]


@dataclass
class PipelineInputs:
    source_id: uuid.UUID
    run_id: str
    schema_id: uuid.UUID
    dataset_name: str
    job_type: ExternalDataSourceType
    team_id: int


async def update_last_synced_at(job_id: str, schema_id: str, team_id: int) -> None:
    @database_sync_to_async_pool
    @retry_on_operational_error
    def _update():
        job = ExternalDataJob.objects.get(pk=job_id)
        schema = ExternalDataSchema.objects.exclude(deleted=True).get(id=schema_id, team_id=team_id)
        schema.last_synced_at = job.created_at
        # Pipeline-internal bookkeeping, not a user edit — skip_activity_log avoids the extra
        # `_get_before_update` SELECT that also needs a pooler connection (see save()).
        schema.save(skip_activity_log=True)

    await _update()


async def set_initial_sync_complete(schema_id: str, team_id: int) -> None:
    await database_sync_to_async_pool(mark_initial_sync_complete)(schema_id=schema_id, team_id=team_id)


def _refresh_cumulative_row_count(table: DataWarehouseTable, logger: FilteringBoundLogger, context: str) -> None:
    # Counting the full S3 dataset can exceed both the chdb and ClickHouse-cluster timeouts on a
    # large table (get_count() then raises). That's only a display stat, not the synced data itself
    # (already written successfully by this point) — keep the previous row_count rather than let it
    # fail the whole table registration.
    try:
        table.row_count = table.get_count()
    except Exception:
        logger.warning(f"Could not refresh cumulative row count for {context}, keeping previous value", exc_info=True)


async def validate_schema_and_update_table(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: Optional[dict[str, str]] = None,
    primary_keys: Optional[list[str]] = None,
) -> None:
    """
    Async version of validate_schema_and_update_table_sync.

    Validates the schemas of data that has been synced by external data job.
    If the schemas are valid, it creates or updates the DataWarehouseTable model with the new url pattern.

    Arguments:
        run_id: The id of the external data job
        team_id: The id of the team
        schema_id: The schema for which the data job relates to
        row_count: The count of synced rows
        table_format: The format of the table
        table_schema_dict: The schema of the table
    """
    logger = LOGGER.bind(team_id=team_id)

    if row_count == 0:
        logger.warning("Skipping `validate_schema_and_update_table` due to `row_count` being 0")
        return

    @database_sync_to_async_pool
    def _validate_and_update():
        job = ExternalDataJob.objects.prefetch_related(
            "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
        ).get(pk=run_id)

        external_data_schema = (
            ExternalDataSchema.objects.prefetch_related("source")
            .exclude(deleted=True)
            .get(id=schema_id, team_id=team_id)
        )

        _schema_id = external_data_schema.id
        _schema_name: str = external_data_schema.name

        # The HogQL table name derives from the raw schema name (only lower-cased); the S3 folder is
        # the snake_cased `s3_folder_name`. They differ on purpose — see `resolve_table_and_folder_names`.
        names = resolve_table_and_folder_names(_schema_name, external_data_schema.resolved_s3_folder_name)
        table_name = build_table_name(job.pipeline, names.table_storage_name)
        new_url_pattern = job.url_pattern_by_schema(names.folder_name)

        try:
            logger.info(f"Row count for {_schema_name} ({_schema_id}) is {row_count}")

            table_params = {
                "name": table_name,
                "format": table_format,
                "url_pattern": new_url_pattern,
                "team_id": team_id,
                "row_count": row_count,
                "queryable_folder": queryable_folder,
            }

            # Resolve (or create) the target table and introspect its ClickHouse schema BEFORE
            # opening a transaction. get_count()/get_columns() hit ClickHouse and retry with
            # backoff when the cluster is degraded — running them inside transaction.atomic()
            # held the Postgres transaction (and the select_for_update row lock below) open for
            # minutes, surfacing as "idle in transaction" connections that stalled vacuum and
            # exhausted the connection pool.
            table_created: DataWarehouseTable | None = external_data_schema.table
            if table_created:
                table = table_created
                table.format = table_params["format"]
                table.url_pattern = new_url_pattern
                table.queryable_folder = queryable_folder
                if external_data_schema.table_row_count_is_cumulative:
                    _refresh_cumulative_row_count(table, logger, f"{_schema_name} ({_schema_id})")
                else:
                    table.row_count = row_count
                # get_count() above can retry against a degraded ClickHouse cluster for minutes, long
                # enough for the pooled Postgres connection to be recycled underneath us. Retry once
                # on a fresh connection rather than let this escape as error-tracking noise.
                # new_url_pattern above is derived from the job's own destination folder, not from
                # request input, so this sync is a trusted writer of a credential-less table's URL.
                retry_on_db_connection_drop(
                    lambda: table.save(
                        update_fields=["format", "url_pattern", "queryable_folder", "row_count"],
                        internally_computed_url_pattern=True,
                    )
                )

            if not table_created:
                # Check if we already have an orphaned table that we can repurpose
                existing_tables = DataWarehouseTable.objects.filter(
                    team_id=team_id, name=table_name, external_data_source_id=job.pipeline.id, deleted=False
                )
                existing_tables_count = existing_tables.count()
                if existing_tables_count > 0:
                    table_created = existing_tables[0]
                    logger.debug(
                        f"Found {existing_tables_count} existing tables - skipping creating and using {table_created.id}"
                    )

                if not table_created:
                    logger.debug(f"Creating table for schema: {str(schema_id)}")
                    table_created = DataWarehouseTable.objects.create(
                        external_data_source_id=job.pipeline.id,
                        created_via=DataWarehouseTable.CreatedVia.SOURCE,
                        **table_params,
                    )

            assert isinstance(table_created, DataWarehouseTable) and table_created is not None

            # safe_expose_ch_error=False keeps failures as ServerException (see except clause below)
            # instead of the generic, user-facing Exception get_columns() raises by default.
            raw_db_columns = table_created.get_columns(safe_expose_ch_error=False)
            db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}

            def _persist_columns() -> None:
                with transaction.atomic():
                    # select_for_update prevents two concurrent sync operations from
                    # causing a lost-update: both would read the current columns,
                    # merge independently, and one write would overwrite the other.
                    # Use raw_objects to skip the default manager's select_related —
                    # its nullable LEFT JOINs are rejected by Postgres under FOR UPDATE.
                    table_for_update = DataWarehouseTable.raw_objects.select_for_update().get(id=table_created.id)
                    existing_columns = table_for_update.columns or {}
                    columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)
                    # Project to enabled_columns so disabled columns the user already deselected don't
                    # creep back into HogQL via the Delta schema (which still contains them historically).
                    # Prefer source-detected PKs (always present) over the schema model's PKs (only set
                    # for CDC and user-picked incremental keys) so non-CDC schemas don't drop their PKs.
                    effective_primary_keys = primary_keys or external_data_schema.primary_key_columns
                    columns = filter_dwh_columns_by_enabled_columns(
                        columns,
                        external_data_schema.enabled_columns,
                        effective_primary_keys,
                        external_data_schema.incremental_field,
                    )
                    table_for_update.columns = columns
                    table_for_update.save(update_fields=["columns"])
                    # Keep local reference in sync
                    table_created.columns = columns

                    # schema could have been deleted by this point
                    schema_model = (
                        ExternalDataSchema.objects.prefetch_related("source")
                        .exclude(deleted=True)
                        .get(id=_schema_id, team_id=team_id)
                    )

                    schema_model.table = table_created
                    schema_model.save()

            # get_columns() above retries against ClickHouse the same way and can also block for
            # minutes, long enough for the pooled connection used by select_for_update() below to go
            # stale. A dropped connection mid-atomic-block rolls the block back, so retrying it whole
            # is safe.
            retry_on_db_connection_drop(_persist_columns)

        except ServerException as err:
            # 636 (CANNOT_EXTRACT_TABLE_STRUCTURE) and 742 (DELTA_KERNEL_ERROR, "No files in log
            # segment") both mean the Delta table has no committed files yet - expected before a
            # schema's first successful sync, or when a run wrote zero new rows.
            if err.code in (636, 742):
                logger.exception(
                    f"Data Warehouse: No data for schema {_schema_name} for external data job {job.pk}",
                    exc_info=err,
                )
            else:
                logger.exception(
                    f"Data Warehouse: Unknown ServerException {job.pk}",
                    exc_info=err,
                )
        except Exception as e:
            # TODO: handle other exceptions here
            logger.exception(
                f"Data Warehouse: Could not validate schema for external data job {job.pk}",
                exc_info=e,
            )
            raise

    await _validate_and_update()


async def register_cdc_companion_table(
    run_id: str,
    team_id: int,
    schema_id: uuid.UUID,
    resource_name: str,
    row_count: int,
    table_format: DataWarehouseTable.TableFormat,
    queryable_folder: str,
    table_schema_dict: Optional[dict[str, str]] = None,
    set_as_schema_table: bool = False,
) -> None:
    """Create or update a standalone DataWarehouseTable for a CDC companion resource (e.g. `{schema_name}_cdc`).

    Unlike `validate_schema_and_update_table`, this does NOT update `schema.table` — the companion table is
    independent of the main schema table so that writing CDC history never overwrites the snapshot queryable folder.

    When ``set_as_schema_table`` is True (used for cdc_only mode), the companion table is also linked as the
    schema's primary table so the UI shows row counts and query links.
    """
    logger = LOGGER.bind(team_id=team_id)

    if row_count == 0:
        await logger.awarning("Skipping `register_cdc_companion_table` due to `row_count` being 0")
        return

    @database_sync_to_async_pool
    def _register():
        job = ExternalDataJob.objects.prefetch_related("pipeline").get(pk=run_id)

        normalized_resource_name = NamingConvention.normalize_identifier(resource_name)
        companion_table_name = build_table_name(job.pipeline, resource_name)
        new_url_pattern = job.url_pattern_by_schema(normalized_resource_name)

        table_params = {
            "name": companion_table_name,
            "format": table_format,
            "url_pattern": new_url_pattern,
            "team_id": team_id,
            "row_count": row_count,
            "queryable_folder": queryable_folder,
        }

        try:
            # Resolve (or create) the companion table and introspect its ClickHouse schema BEFORE
            # opening a transaction — get_count()/get_columns() hit ClickHouse and can take minutes
            # when the cluster is degraded, so holding a Postgres transaction open across them is
            # what produced minutes-long "idle in transaction" connections.
            # Find existing companion table (not schema.table) by name
            companion_table: DataWarehouseTable | None = DataWarehouseTable.objects.filter(
                team_id=team_id,
                name=companion_table_name,
                external_data_source_id=job.pipeline.id,
                deleted=False,
            ).first()

            if companion_table:
                table = companion_table
                table.format = table_format
                table.url_pattern = new_url_pattern
                table.queryable_folder = queryable_folder
                _refresh_cumulative_row_count(table, logger, companion_table_name)
                # Scope to the fields changed here so this out-of-transaction save doesn't rewrite
                # `columns` with its pre-merge value before the column save below.
                # get_count() above can retry against a degraded ClickHouse cluster for minutes, long
                # enough for the pooled Postgres connection to be recycled underneath us. Retry once
                # on a fresh connection rather than let this escape as error-tracking noise.
                # new_url_pattern above is derived from the job's own destination folder, not from
                # request input, so this sync is a trusted writer of a credential-less table's URL.
                retry_on_db_connection_drop(
                    lambda: table.save(
                        update_fields=["format", "url_pattern", "queryable_folder", "row_count"],
                        internally_computed_url_pattern=True,
                    )
                )
            else:
                logger.debug(f"Creating CDC companion table: {companion_table_name}")
                companion_table = DataWarehouseTable.objects.create(
                    external_data_source_id=job.pipeline.id,
                    created_via=DataWarehouseTable.CreatedVia.SOURCE,
                    **table_params,
                )

            raw_db_columns = companion_table.get_columns()
            db_columns = {key: str(column.get("clickhouse", "")) for key, column in raw_db_columns.items()}
            existing_columns = companion_table.columns or {}
            columns = merge_columns(db_columns, table_schema_dict or {}, existing_columns)

            def _persist_columns() -> None:
                with transaction.atomic():
                    companion_table.columns = columns
                    companion_table.save(update_fields=["columns"])

                    if set_as_schema_table:
                        ExternalDataSchema.objects.filter(id=schema_id, team_id=team_id).update(table=companion_table)

            # get_columns() above retries against ClickHouse the same way and can also block for
            # minutes, long enough for the pooled connection to go stale. A dropped connection rolls
            # the atomic block back, so retrying it whole is safe.
            retry_on_db_connection_drop(_persist_columns)

        except Exception as e:
            logger.exception(
                f"Data Warehouse: Could not register CDC companion table {companion_table_name}",
                exc_info=e,
            )
            raise

    await _register()
