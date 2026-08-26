"""
Facade for warehouse_sources.

Capability-oriented read functions that map ORM instances to framework-free
contracts (``facade/contracts.py``) — the facade never returns ORM across the
boundary. Mappers are explicit so the consumed shape is visible in one place.

Heavy HogQL-adjacent wiring (model classes, table resolution, ClickHouse→HogQL
type mappings) lives in ``facade/hogql.py``; temporal/source wiring in
``facade/temporal.py``. This module re-exports only the framework-free helper
transforms (prefix/URL validation, column converters) so config-only consumers
don't drag heavy imports onto the ``django.setup()`` path.

Write paths (create/update of sources, schemas, tables, jobs) remain inside
``products/data_warehouse`` for now — a legacy-leak swept in Phase 2 — so this
first facade serves the read consumers and the framework-free helpers.
"""

from collections.abc import Collection
from uuid import UUID

from django.db.models import Prefetch, QuerySet

# Source-agnostic storage contract for user-uploaded files — shared with the upload endpoint.
from products.warehouse_sources.backend.file_uploads import (
    FILE_FORMAT_READ_HINTS,
    FILE_FORMAT_TO_TABLE_FORMAT,
    MAX_UPLOAD_SIZE_BYTES as MAX_FILE_UPLOAD_SIZE_BYTES,
    SUPPORTED_FILE_FORMATS,
    build_file_upload_s3_key,
    build_file_upload_s3_path,
    build_file_upload_url_pattern,
    hosted_upload_s3_path,
)
from products.warehouse_sources.backend.models.column_statistics import (
    WarehouseColumnStatistics as _WarehouseColumnStatistics,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob as _ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema as _ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource as _ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable as _DataWarehouseTable

# Framework-free helper transforms — re-exported as the public helper surface.
from products.warehouse_sources.backend.models.util import (
    clickhouse_columns_to_dwh_columns,
    get_view_or_table_by_name as _get_view_or_table_by_name,
    motherduck_columns_to_dwh_columns,
    mysql_column_to_dwh_column,
    mysql_columns_to_dwh_columns,
    postgres_column_to_dwh_column,
    postgres_columns_to_dwh_columns,
    snowflake_columns_to_dwh_columns,
    validate_source_prefix,
    validate_warehouse_table_url_pattern,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

from . import contracts

__all__ = [
    # capability functions
    "get_source",
    "list_sources",
    "list_revenue_sources",
    "list_revenue_source_settings",
    "get_schema",
    "list_schemas_for_source",
    "source_locations_for_tables",
    "get_table",
    "get_queryable_table",
    "resolve_object_by_name",
    "list_tables_for_source",
    "list_jobs_for_source",
    "list_column_statistics",
    # framework-free helper transforms
    "clickhouse_columns_to_dwh_columns",
    "motherduck_columns_to_dwh_columns",
    "mysql_column_to_dwh_column",
    "mysql_columns_to_dwh_columns",
    "postgres_column_to_dwh_column",
    "postgres_columns_to_dwh_columns",
    "snowflake_columns_to_dwh_columns",
    "validate_source_prefix",
    "validate_warehouse_table_url_pattern",
    # file-upload storage contract
    "FILE_FORMAT_READ_HINTS",
    "FILE_FORMAT_TO_TABLE_FORMAT",
    "MAX_FILE_UPLOAD_SIZE_BYTES",
    "SUPPORTED_FILE_FORMATS",
    "build_file_upload_s3_key",
    "build_file_upload_s3_path",
    "build_file_upload_url_pattern",
    "hosted_upload_s3_path",
]

# GitHub multi-repo source helpers live in ``github_warehouse_repos`` and pull the source
# registry (dlt drivers) in via ``facade.source_management``, so resolve them lazily to keep that
# weight off the ``django.setup()`` import path — only the namespaced-resource registry loads them.
_LAZY = {
    "github_repositories_for_job_inputs": "github_warehouse_repos",
    "reconcile_github_repositories": "github_warehouse_repos",
}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(f"products.warehouse_sources.backend.{module}"), name)


# --- Mappers (ORM -> contract) ---


def _to_source(source: _ExternalDataSource) -> contracts.ExternalDataSource:
    return contracts.ExternalDataSource(
        id=source.id,
        team_id=source.team_id,
        source_type=source.source_type,
        status=source.status,
        prefix=source.prefix,
        access_method=source.access_method,
        direct_query_enabled=source.direct_query_enabled,
        created_via=source.created_via,
        created_at=source.created_at,
        updated_at=source.updated_at,
        is_direct_query=source.is_direct_query,
        is_direct_postgres=source.is_direct_postgres,
        is_direct_mysql=source.is_direct_mysql,
        direct_engine=source.direct_engine,
    )


def _to_revenue_source(source: _ExternalDataSource) -> contracts.RevenueSource:
    settings = getattr(source, "revenue_analytics_config", None)
    return contracts.RevenueSource(
        id=source.id,
        source_type=source.source_type,
        prefix=source.prefix,
        enabled=settings.enabled if settings is not None else source.source_type == ExternalDataSourceType.STRIPE,
        include_invoiceless_charges=settings.include_invoiceless_charges if settings is not None else True,
        schemas=tuple(
            contracts.RevenueSourceSchema(
                name=schema.name,
                table=(
                    contracts.RevenueSourceTable(id=schema.table.id, name=schema.table.name)
                    if schema.table is not None and schema.table.team_id == schema.team_id
                    else None
                ),
            )
            for schema in source.schemas.all()
        ),
    )


def _to_revenue_source_settings(source: _ExternalDataSource) -> contracts.RevenueSourceSettings:
    settings = getattr(source, "revenue_analytics_config", None)
    return contracts.RevenueSourceSettings(
        id=source.id,
        source_type=source.source_type,
        prefix=source.prefix,
        deleted=bool(source.deleted),
        enabled=settings.enabled if settings is not None else source.source_type == ExternalDataSourceType.STRIPE,
    )


def _to_schema(schema: _ExternalDataSchema) -> contracts.ExternalDataSchema:
    return contracts.ExternalDataSchema(
        id=schema.id,
        team_id=schema.team_id,
        source_id=schema.source_id,
        table_id=schema.table_id,
        name=schema.name,
        label=schema.label,
        status=schema.status,
        should_sync=schema.should_sync,
        latest_error=schema.latest_error,
        last_synced_at=schema.last_synced_at,
        sync_type=schema.sync_type,
        sync_frequency_interval=schema.sync_frequency_interval,
        sync_time_of_day=schema.sync_time_of_day,
        initial_sync_complete=schema.initial_sync_complete,
        description=schema.description,
        created_at=schema.created_at,
        updated_at=schema.updated_at,
        normalized_name=schema.normalized_name,
        is_incremental=schema.is_incremental,
        is_cdc=schema.is_cdc,
        source_type=schema.source.source_type if schema.source_id else None,
    )


def _to_table(table: _DataWarehouseTable) -> contracts.DataWarehouseTable:
    return contracts.DataWarehouseTable(
        id=table.id,
        team_id=table.team_id,
        name=table.name,
        format=table.format,
        url_pattern=table.url_pattern,
        queryable_folder=table.queryable_folder,
        columns=table.columns or {},
        row_count=table.row_count,
        size_in_s3_mib=table.size_in_s3_mib,
        external_data_source_id=table.external_data_source_id,
        credential_id=table.credential_id,
        created_at=table.created_at,
    )


def _to_job(job: _ExternalDataJob) -> contracts.ExternalDataJob:
    pipeline = job.pipeline if job.pipeline_id else None
    return contracts.ExternalDataJob(
        id=job.id,
        team_id=job.team_id,
        status=job.status,
        latest_error=job.latest_error,
        finished_at=job.finished_at,
        rows_synced=job.rows_synced or 0,
        billable=job.billable,
        schema_id=job.schema_id,
        pipeline_id=job.pipeline_id,
        workflow_id=job.workflow_id,
        workflow_run_id=job.workflow_run_id,
        created_at=job.created_at,
        source_type=pipeline.source_type if pipeline else None,
        source_prefix=pipeline.prefix if pipeline else None,
    )


# --- Capability functions (read) ---


def get_source(source_id: UUID, team_id: int) -> contracts.ExternalDataSource:
    return _to_source(_ExternalDataSource.objects.get(id=source_id, team_id=team_id))


def list_sources(
    team_id: int,
    *,
    include_deleted: bool = False,
) -> list[contracts.ExternalDataSource]:
    qs = _ExternalDataSource.objects.filter(team_id=team_id)
    if not include_deleted:
        qs = qs.exclude(deleted=True)
    return [_to_source(s) for s in qs]


def _revenue_source_queryset(
    team_id: int,
    *,
    include_deleted: bool,
    source_types: Collection[str] | None,
    source_ids: Collection[UUID] | None,
) -> QuerySet[_ExternalDataSource]:
    sources = _ExternalDataSource.objects.select_related("revenue_analytics_config").filter(team_id=team_id)
    if not include_deleted:
        sources = sources.exclude(deleted=True)
    if source_types is not None:
        sources = sources.filter(source_type__in=source_types)
    if source_ids is not None:
        sources = sources.filter(id__in=source_ids)
    return sources


def list_revenue_sources(
    team_id: int,
    *,
    source_types: Collection[str] | None = None,
) -> list[contracts.RevenueSource]:
    schemas = _ExternalDataSchema.objects.select_related("table").filter(team_id=team_id)
    sources = _revenue_source_queryset(
        team_id,
        include_deleted=False,
        source_types=source_types,
        source_ids=None,
    ).prefetch_related(Prefetch("schemas", queryset=schemas))
    return [_to_revenue_source(source) for source in sources]


def list_revenue_source_settings(
    team_id: int,
    *,
    include_deleted: bool = False,
    source_types: Collection[str] | None = None,
    source_ids: Collection[UUID] | None = None,
) -> list[contracts.RevenueSourceSettings]:
    sources = _revenue_source_queryset(
        team_id,
        include_deleted=include_deleted,
        source_types=source_types,
        source_ids=source_ids,
    )
    return [_to_revenue_source_settings(source) for source in sources]


def get_schema(schema_id: UUID, team_id: int) -> contracts.ExternalDataSchema:
    return _to_schema(_ExternalDataSchema.objects.select_related("source").get(id=schema_id, team_id=team_id))


def list_schemas_for_source(source_id: UUID, team_id: int) -> list[contracts.ExternalDataSchema]:
    qs = _ExternalDataSchema.objects.select_related("source").filter(team_id=team_id, source_id=source_id)
    return [_to_schema(s) for s in qs]


def source_locations_for_tables(team_id: int, table_ids: Collection[UUID]) -> dict[UUID, contracts.TableSourceLocation]:
    """Where each of these tables is administered. One query, and tables with no schema are absent."""
    if not table_ids:
        return {}
    rows = _ExternalDataSchema.objects.filter(
        team_id=team_id, table_id__in=list(table_ids), source_id__isnull=False
    ).values_list("table_id", "source_id", "id")
    return {
        table_id: contracts.TableSourceLocation(source_id=source_id, schema_id=schema_id)
        for table_id, source_id, schema_id in rows
    }


def get_table(table_id: UUID, team_id: int) -> contracts.DataWarehouseTable:
    return _to_table(_DataWarehouseTable.objects.get(id=table_id, team_id=team_id))


def get_queryable_table(table_id: UUID, team_id: int) -> contracts.DataWarehouseTable | None:
    """The table only if it is still queryable, else None.

    Unlike ``get_table``, this applies the soft-delete and orphaned-source filters and returns
    None instead of raising, so a caller holding a stored table reference can tell "gone" from
    "something went wrong".
    """
    # raw_objects skips the eager schema prefetch/joins objects does -- the mapper only reads scalars.
    table = _DataWarehouseTable.raw_objects.queryable().filter(id=table_id, team_id=team_id).first()
    return _to_table(table) if table is not None else None


def resolve_object_by_name(team_id: int, name: str) -> contracts.WarehouseObjectRef | None:
    """The warehouse table or saved query a query reaches under this name, else None.

    Resolves the dotted source forms (``stripe.charges``) the same way a query does, and skips
    soft-deleted rows and orphans of a deleted source. None means the name reaches neither, so it
    carries no object-level access control -- a PostHog table such as ``events``, or nothing at all.

    For a caller recording what a query read: the identity survives the name being freed and taken
    by something else, which is what makes it usable as evidence later.
    """
    resolved = _get_view_or_table_by_name(team_id, name)
    if resolved is None:
        return None
    kind = (
        contracts.WAREHOUSE_OBJECT_TABLE
        if isinstance(resolved, _DataWarehouseTable)
        else contracts.WAREHOUSE_OBJECT_VIEW
    )
    return contracts.WarehouseObjectRef(kind=kind, id=resolved.id)


def list_tables_for_source(source_id: UUID, team_id: int) -> list[contracts.DataWarehouseTable]:
    qs = _DataWarehouseTable.objects.filter(team_id=team_id, external_data_source_id=source_id).exclude(deleted=True)
    return [_to_table(t) for t in qs]


def list_jobs_for_source(source_id: UUID, team_id: int) -> list[contracts.ExternalDataJob]:
    qs = (
        _ExternalDataJob.objects.select_related("schema", "pipeline")
        .filter(team_id=team_id, pipeline_id=source_id)
        .order_by("-created_at")
    )
    return [_to_job(j) for j in qs]


def list_column_statistics(team_id: int) -> list[contracts.ColumnStatistics]:
    """Every column profile for a team, for describing warehouse tables in a query schema."""
    qs = _WarehouseColumnStatistics.objects.for_team(team_id).values_list(
        "table_id", "column_name", "null_fraction", "min_value", "max_value"
    )
    return [
        contracts.ColumnStatistics(
            table_id=table_id,
            column_name=column_name,
            null_fraction=null_fraction,
            min_value=min_value,
            max_value=max_value,
        )
        for table_id, column_name, null_fraction, min_value, max_value in qs
    ]
