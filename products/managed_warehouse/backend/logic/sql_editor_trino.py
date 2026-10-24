from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import structlog

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.database.direct_trino_table import is_managed_trino_external_catalog
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.trino_adapter import (
    DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    TrinoQueryRequest,
    bounded_trino_cursor,
    ensure_read_only_raw_trino_statement,
    execute_trino_query,
)
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.escape_sql import escape_trino_identifier

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
from products.managed_warehouse.backend.logic.sql_editor import managed_warehouse_sql_editor_uses_trino
from products.managed_warehouse.backend.storage_location import normalize_s3_location
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.warehouse_sources.backend.facade.source_management import SourceSchema, discover_trino_catalog

if TYPE_CHECKING:
    from trino.dbapi import Connection

    from posthog.models import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


logger = structlog.get_logger(__name__)

MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS = 60
EXTERNAL_TRINO_CATALOG_DISCOVERY_TIMEOUT_SECONDS = 20
EXTERNAL_TRINO_DISCOVERY_BUDGET_SECONDS = 60
MAX_EXTERNAL_TRINO_CATALOGS = 20
MAX_EXTERNAL_TRINO_TABLES_PER_CATALOG = 5000
# Trino's information_schema has no table location, so each one costs a SHOW CREATE TABLE,
# which reads the table's Delta log. A separate budget keeps it from starving table discovery.
EXTERNAL_TRINO_LOCATION_TIMEOUT_SECONDS = 5
EXTERNAL_TRINO_LOCATION_BUDGET_SECONDS = 30
MAX_EXTERNAL_TRINO_LOCATION_LOOKUPS = 500

_SHOW_CREATE_LOCATION_RE = re.compile(r"\blocation\s*=\s*'((?:[^']|'')*)'")


class ManagedTrinoAdapter:
    engine = "trino"
    dialect: HogQLDialect | None = "trino"

    def prepare_raw_sql(self, sql: str) -> str:
        return ensure_read_only_raw_trino_statement(sql)

    # nosemgrep: tuple-return-prefer-dataclass -- DirectSQLAdapter requires an implementation/config tuple.
    def validate_source_config(self, source: ExternalDataSource, team: Team) -> tuple[None, None]:
        if (
            source.team_id != team.pk
            or source.deleted
            or not source.is_dynamic_managed_warehouse
            or not managed_warehouse_sql_editor_uses_trino(team.organization_id)
        ):
            raise ExposedHogQLError(
                "This managed Trino connection is unavailable. Refresh the SQL editor and try again."
            )
        return None, None

    def execute(self, request: DirectQueryRequest) -> DirectQueryResult:
        self.validate_source_config(request.source, request.team)
        if request.principal is None:
            raise ExposedHogQLError("Sign in to query the managed warehouse.")
        try:
            return execute_trino_query(
                TrinoQueryRequest(
                    sql=request.sql,
                    values=request.values,
                    timeout_seconds=request.settings.max_execution_time
                    or DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
                    timings=request.timings,
                    team_id=request.team.pk,
                    debug=request.debug,
                    cancellation_token=request.cancellation_token,
                ),
                connect_managed_warehouse_trino(str(request.team.organization_id), principal=request.principal.value),
            )
        except (ExposedHogQLError, ManagedWarehouseTrinoConnectionUnavailable) as error:
            if not isinstance(error, ManagedWarehouseTrinoConnectionUnavailable) and not isinstance(
                error.__cause__, ManagedWarehouseTrinoConnectionUnavailable
            ):
                raise
            raise ExposedHogQLError("Trino is not ready for this warehouse. Try again later.") from error


@frozen
class ManagedTrinoDiscovery:
    schemas: list[SourceSchema]
    # External catalogs whose discovery failed. Reconcile keeps their existing tables
    # instead of deleting them, so one slow catalog cannot hide its tables from HogQL.
    unavailable_catalogs: frozenset[str]
    # Normalized s3:// root per external table name. A table without one maps no warehouse table.
    table_locations: dict[str, str]


def external_trino_table_name(catalog: str, schema: str, table: str) -> str:
    """The HogQL name of a table in an external catalog.

    Primary catalog tables are `schema.table`. The catalog prefix keeps external names in a
    separate namespace, and the name is also the Trino reference, so a query reads the same in both.
    """
    return f"{catalog}.{schema}.{table}"


def discover_managed_trino_schemas(organization_id: str, team_id: int) -> ManagedTrinoDiscovery:
    with connect_managed_warehouse_trino(
        organization_id, principal=f"posthog:sql-editor-schema-discovery:team:{team_id}"
    ) as connection:
        with bounded_trino_cursor(connection, MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS, team_id=team_id) as (
            cursor,
            watchdog,
        ):
            if not connection.catalog:
                raise ManagedWarehouseTrinoConnectionUnavailable("Trino did not return a warehouse catalog")
            tables = discover_trino_catalog(cursor, catalog=connection.catalog)
            watchdog.check()
            cursor.execute("SHOW CATALOGS")
            external_catalogs = sorted(
                str(row[0]) for row in cursor.fetchall() if is_managed_trino_external_catalog(str(row[0]))
            )
            watchdog.check()
        schemas = [
            SourceSchema(
                name=f"{table.schema}.{table.name}",
                supports_incremental=False,
                supports_append=False,
                columns=[(column.name, column.data_type, column.nullable) for column in table.columns],
                source_catalog=table.catalog,
                source_schema=table.schema,
                source_table_name=table.name,
            )
            for table in tables
        ]
        unavailable: set[str] = set(external_catalogs[MAX_EXTERNAL_TRINO_CATALOGS:])
        if unavailable:
            logger.warning("managed_warehouse.external_catalogs_over_limit", team_id=team_id, skipped=len(unavailable))
        deadline = time.monotonic() + EXTERNAL_TRINO_DISCOVERY_BUDGET_SECONDS
        for catalog in external_catalogs[:MAX_EXTERNAL_TRINO_CATALOGS]:
            if time.monotonic() >= deadline:
                unavailable.add(catalog)
                continue
            try:
                schemas.extend(_discover_external_catalog(connection, catalog, team_id))
            except Exception as error:
                # Not sent to error tracking: captured frames would hold the service credential.
                unavailable.add(catalog)
                logger.warning(
                    "managed_warehouse.external_catalog_discovery_failed",
                    team_id=team_id,
                    catalog=catalog,
                    error_type=type(error).__name__,
                )
        external_tables = [
            schema for schema in schemas if is_managed_trino_external_catalog(schema.source_catalog or "")
        ]
        table_locations = _read_external_table_locations(connection, external_tables, team_id)
    return ManagedTrinoDiscovery(
        schemas=schemas, unavailable_catalogs=frozenset(unavailable), table_locations=table_locations
    )


def _read_external_table_locations(connection: Connection, tables: list[SourceSchema], team_id: int) -> dict[str, str]:
    locations: dict[str, str] = {}
    failed = 0
    deadline = time.monotonic() + EXTERNAL_TRINO_LOCATION_BUDGET_SECONDS
    lookups = tables[:MAX_EXTERNAL_TRINO_LOCATION_LOOKUPS]
    for index, table in enumerate(lookups):
        if time.monotonic() >= deadline:
            failed += len(lookups) - index
            break
        try:
            location = _read_external_table_location(connection, table, team_id)
        except Exception:
            # Not sent to error tracking: captured frames would hold the service credential.
            failed += 1
            continue
        if location is not None:
            locations[table.name] = location
    skipped = len(tables) - len(lookups)
    if failed or skipped:
        logger.warning(
            "managed_warehouse.external_table_locations_incomplete", team_id=team_id, failed=failed, skipped=skipped
        )
    return locations


def _read_external_table_location(connection: Connection, table: SourceSchema, team_id: int) -> str | None:
    reference = ".".join(
        escape_trino_identifier(part)
        for part in (table.source_catalog or "", table.source_schema or "", table.source_table_name or "")
    )
    with bounded_trino_cursor(connection, EXTERNAL_TRINO_LOCATION_TIMEOUT_SECONDS, team_id=team_id) as (
        cursor,
        watchdog,
    ):
        cursor.execute(f"SHOW CREATE TABLE {reference}")
        rows = cursor.fetchall()
        watchdog.check()
    return location_from_show_create_table(str(rows[0][0])) if rows else None


def location_from_show_create_table(statement: str) -> str | None:
    # Table properties follow the column list, so the last match is the table's own location
    # even when a column comment mentions one.
    matches = _SHOW_CREATE_LOCATION_RE.findall(statement)
    if not matches:
        return None
    return normalize_s3_location(matches[-1].replace("''", "'"))


def _discover_external_catalog(connection: Connection, catalog: str, team_id: int) -> list[SourceSchema]:
    with bounded_trino_cursor(connection, EXTERNAL_TRINO_CATALOG_DISCOVERY_TIMEOUT_SECONDS, team_id=team_id) as (
        cursor,
        watchdog,
    ):
        tables = discover_trino_catalog(cursor, catalog=catalog)
        watchdog.check()
    if len(tables) > MAX_EXTERNAL_TRINO_TABLES_PER_CATALOG:
        raise ValueError(f"External catalog has more than {MAX_EXTERNAL_TRINO_TABLES_PER_CATALOG} tables")
    return [
        SourceSchema(
            name=external_trino_table_name(catalog, table.schema, table.name),
            supports_incremental=False,
            supports_append=False,
            columns=[(column.name, column.data_type, column.nullable) for column in table.columns],
            source_catalog=catalog,
            source_schema=table.schema,
            source_table_name=table.name,
        )
        for table in tables
    ]
