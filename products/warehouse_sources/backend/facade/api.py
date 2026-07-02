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

from uuid import UUID

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob as _ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema as _ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource as _ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable as _DataWarehouseTable

# Framework-free helper transforms — re-exported as the public helper surface.
from products.warehouse_sources.backend.models.util import (
    mysql_column_to_dwh_column,
    mysql_columns_to_dwh_columns,
    postgres_column_to_dwh_column,
    postgres_columns_to_dwh_columns,
    snowflake_columns_to_dwh_columns,
    validate_source_prefix,
    validate_warehouse_table_url_pattern,
)

from . import contracts

__all__ = [
    # capability functions
    "get_source",
    "list_sources",
    "get_schema",
    "list_schemas_for_source",
    "get_table",
    "list_tables_for_source",
    "list_jobs_for_source",
    # framework-free helper transforms
    "mysql_column_to_dwh_column",
    "mysql_columns_to_dwh_columns",
    "postgres_column_to_dwh_column",
    "postgres_columns_to_dwh_columns",
    "snowflake_columns_to_dwh_columns",
    "validate_source_prefix",
    "validate_warehouse_table_url_pattern",
]

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


def list_sources(team_id: int, *, include_deleted: bool = False) -> list[contracts.ExternalDataSource]:
    qs = _ExternalDataSource.objects.filter(team_id=team_id)
    if not include_deleted:
        qs = qs.exclude(deleted=True)
    return [_to_source(s) for s in qs]


def get_schema(schema_id: UUID, team_id: int) -> contracts.ExternalDataSchema:
    return _to_schema(_ExternalDataSchema.objects.select_related("source").get(id=schema_id, team_id=team_id))


def list_schemas_for_source(source_id: UUID, team_id: int) -> list[contracts.ExternalDataSchema]:
    qs = _ExternalDataSchema.objects.select_related("source").filter(team_id=team_id, source_id=source_id)
    return [_to_schema(s) for s in qs]


def get_table(table_id: UUID, team_id: int) -> contracts.DataWarehouseTable:
    return _to_table(_DataWarehouseTable.objects.get(id=table_id, team_id=team_id))


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
