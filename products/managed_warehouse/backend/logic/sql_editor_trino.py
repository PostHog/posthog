from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql.constants import HogQLDialect
from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult
from posthog.hogql.direct_sql.trino_adapter import (
    DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    TrinoQueryRequest,
    bounded_trino_cursor,
    ensure_read_only_raw_trino_statement,
    execute_trino_query,
)
from posthog.hogql.errors import ExposedHogQLError

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
from products.managed_warehouse.backend.logic.sql_editor import managed_warehouse_sql_editor_uses_trino
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.warehouse_sources.backend.facade.source_management import SourceSchema, discover_trino_catalog

if TYPE_CHECKING:
    from posthog.models import Team

    from products.warehouse_sources.backend.facade.models import ExternalDataSource


MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS = 60


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


def discover_managed_trino_schemas(organization_id: str, team_id: int) -> list[SourceSchema]:
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
    return [
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
