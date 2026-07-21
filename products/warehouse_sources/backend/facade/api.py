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

from collections import defaultdict
from collections.abc import Collection
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Max, Q, Sum
from django.utils import timezone

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
    "list_tables_by_names",
    "list_schemas_for_tables",
    "list_jobs_for_source",
    "get_latest_job",
    "get_source_health",
    "list_source_health",
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


def list_jobs_for_source(source_id: UUID, team_id: int, *, limit: int | None = 100) -> list[contracts.ExternalDataJob]:
    # Bounded by default: long-lived sources accumulate thousands of job rows, and an
    # unbounded list materializes a contract per row. Pass limit=None deliberately.
    qs = (
        _ExternalDataJob.objects.select_related("schema", "pipeline")
        .filter(team_id=team_id, pipeline_id=source_id)
        .order_by("-created_at")
    )
    if limit is not None:
        qs = qs[:limit]
    return [_to_job(j) for j in qs]


def get_latest_job(
    team_id: int,
    *,
    source_id: UUID | None = None,
    schema_id: UUID | None = None,
    status: str | None = None,
) -> contracts.ExternalDataJob | None:
    qs = _ExternalDataJob.objects.select_related("schema", "pipeline").filter(team_id=team_id)
    if source_id is not None:
        qs = qs.filter(pipeline_id=source_id)
    if schema_id is not None:
        qs = qs.filter(schema_id=schema_id)
    if status is not None:
        qs = qs.filter(status=status)
    job = qs.order_by("-created_at").first()
    return _to_job(job) if job is not None else None


def list_tables_by_names(team_id: int, names: Collection[str]) -> list[contracts.DataWarehouseTable]:
    qs = _DataWarehouseTable.objects.filter(team_id=team_id, name__in=names).exclude(deleted=True)
    return [_to_table(t) for t in qs]


def list_schemas_for_tables(team_id: int, table_ids: Collection[UUID]) -> list[contracts.ExternalDataSchema]:
    qs = _ExternalDataSchema.objects.select_related("source").filter(team_id=team_id, table_id__in=table_ids)
    return [_to_schema(s) for s in qs]


# --- Source health ---

DEFAULT_STALE_THRESHOLD = timedelta(hours=24)


def get_source_health(
    source_id: UUID,
    team_id: int,
    *,
    stale_threshold: timedelta = DEFAULT_STALE_THRESHOLD,
    required_schema_names: list[str] | None = None,
) -> contracts.SourceHealth:
    source = _ExternalDataSource.objects.get(id=source_id, team_id=team_id)
    required_by_type = {source.source_type: required_schema_names} if required_schema_names is not None else None
    return _build_health([source], stale_threshold=stale_threshold, required_by_type=required_by_type)[0]


def list_source_health(
    team_id: int,
    *,
    source_types: list[str] | None = None,
    stale_threshold: timedelta = DEFAULT_STALE_THRESHOLD,
    required_schema_names_by_type: dict[str, list[str]] | None = None,
) -> list[contracts.SourceHealth]:
    qs = _ExternalDataSource.objects.filter(team_id=team_id).exclude(deleted=True)
    if source_types is not None:
        qs = qs.filter(source_type__in=source_types)
    return _build_health(
        list(qs.order_by("source_type", "-created_at")),
        stale_threshold=stale_threshold,
        required_by_type=required_schema_names_by_type,
    )


def _build_health(
    sources: list[_ExternalDataSource],
    *,
    stale_threshold: timedelta,
    required_by_type: dict[str, list[str] | None] | None,
) -> list[contracts.SourceHealth]:
    # Set-based on purpose: a fixed 3 queries for any number of sources (schemas,
    # completed-job aggregate, newest-failed-job per source) — never per-source loops.
    if not sources:
        return []
    source_ids = [s.id for s in sources]
    now = timezone.now()

    schemas_by_source: dict[UUID, list[_ExternalDataSchema]] = defaultdict(list)
    for schema in _ExternalDataSchema.objects.filter(source_id__in=source_ids).exclude(deleted=True):
        schemas_by_source[schema.source_id].append(schema)

    completed_by_source = {
        row["pipeline_id"]: row
        for row in _ExternalDataJob.objects.filter(pipeline_id__in=source_ids, status=_ExternalDataJob.Status.COMPLETED)
        .values("pipeline_id")
        .annotate(
            last_completed=Max("finished_at"),
            rows_24h=Sum("rows_synced", filter=Q(finished_at__gte=now - timedelta(hours=24))),
            rows_7d=Sum("rows_synced", filter=Q(finished_at__gte=now - timedelta(days=7))),
        )
    }
    # Newest failed job with an error, per source (Postgres DISTINCT ON).
    failed_by_source = {
        row["pipeline_id"]: row
        for row in _ExternalDataJob.objects.filter(
            pipeline_id__in=source_ids,
            status=_ExternalDataJob.Status.FAILED,
            latest_error__isnull=False,
        )
        .order_by("pipeline_id", "-created_at")
        .distinct("pipeline_id")
        .values("pipeline_id", "created_at", "latest_error")
    }

    out: list[contracts.SourceHealth] = []
    for source in sources:
        completed = completed_by_source.get(source.id)
        last_completed_at = completed["last_completed"] if completed else None

        failed = failed_by_source.get(source.id)
        # An error is only "unresolved" while no later sync has completed.
        error_text: str | None = None
        if failed is not None and (last_completed_at is None or failed["created_at"] > last_completed_at):
            error_text = failed["latest_error"]

        required_names = (required_by_type or {}).get(source.source_type)
        schema_healths = _schema_healths(schemas_by_source.get(source.id, []), required_names)

        out.append(
            contracts.SourceHealth(
                source_id=source.id,
                team_id=source.team_id,
                source_type=source.source_type,
                prefix=source.prefix,
                created_at=source.created_at,
                sync_status=_resolve_sync_status(
                    last_completed_at=last_completed_at,
                    error_text=error_text,
                    schema_healths=schema_healths,
                    has_required_names=required_names is not None,
                    now=now,
                    stale_threshold=stale_threshold,
                ),
                last_completed_sync_at=last_completed_at,
                last_unresolved_error=error_text,
                rows_synced_last_24h=int((completed or {}).get("rows_24h") or 0),
                rows_synced_last_7d=int((completed or {}).get("rows_7d") or 0),
                schemas=schema_healths,
            )
        )
    return out


def _schema_healths(
    schemas: list[_ExternalDataSchema], required_names: list[str] | None
) -> list[contracts.SchemaHealth]:
    if required_names is None:
        return [
            contracts.SchemaHealth(
                schema_name=s.name,
                present=True,
                should_sync=s.should_sync,
                status=s.status,
                last_synced_at=s.last_synced_at,
            )
            for s in schemas
        ]
    by_name = {s.name: s for s in schemas}
    out: list[contracts.SchemaHealth] = []
    for name in required_names:
        schema = by_name.get(name)
        if schema is None:
            out.append(
                contracts.SchemaHealth(
                    schema_name=name, present=False, should_sync=False, status=None, last_synced_at=None
                )
            )
        else:
            out.append(
                contracts.SchemaHealth(
                    schema_name=name,
                    present=True,
                    should_sync=schema.should_sync,
                    status=schema.status,
                    last_synced_at=schema.last_synced_at,
                )
            )
    return out


def _resolve_sync_status(
    *,
    last_completed_at: datetime | None,
    error_text: str | None,
    schema_healths: list[contracts.SchemaHealth],
    has_required_names: bool,
    now: datetime,
    stale_threshold: timedelta,
) -> contracts.SyncStatus:
    # Schema-level states outrank job-level ones, but only against the caller's
    # required names — without them a Failed optional schema must not mask "ok".
    if has_required_names:
        if any(not s.present for s in schema_healths):
            return "tables_missing"
        if any(s.status == _ExternalDataSchema.Status.FAILED for s in schema_healths):
            return "tables_failed"
        if any(s.present and not s.should_sync for s in schema_healths):
            return "tables_disabled"
    if error_text is not None:
        return "error"
    if last_completed_at is None:
        return "never"
    if now - last_completed_at > stale_threshold:
        return "stale"
    return "ok"
