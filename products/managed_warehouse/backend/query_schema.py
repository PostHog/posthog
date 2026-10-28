from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSerializedFieldType,
    HogQLQuery,
)

from posthog.hogql.direct_sql.trino_adapter import bounded_trino_cursor
from posthog.hogql.escape_sql import quote_hogql_identifier

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTrinoConnectionUnavailable
from products.managed_warehouse.backend.logic.sql_editor_trino import MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS
from products.managed_warehouse.backend.query_execution import validate_managed_trino_query
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.warehouse_sources.backend.facade.models import trino_column_to_dwh_column
from products.warehouse_sources.backend.facade.source_management import discover_trino_catalog

if TYPE_CHECKING:
    from posthog.models import Team, User


def get_managed_trino_schema(
    query: DatabaseSchemaQuery, *, team: Team, user: User | None
) -> DatabaseSchemaQueryResponse:
    validate_managed_trino_query(
        HogQLQuery(
            query="SELECT 1", executionTarget="managed_trino", connectionId=query.connectionId, sendRawQuery=True
        ),
        team,
        user,
    )
    assert user is not None
    with connect_managed_warehouse_trino(
        str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}"
    ) as connection:
        with bounded_trino_cursor(connection, MANAGED_TRINO_SCHEMA_DISCOVERY_TIMEOUT_SECONDS, team_id=team.pk) as (
            cursor,
            watchdog,
        ):
            if not connection.catalog:
                raise ManagedWarehouseTrinoConnectionUnavailable("Trino did not return a warehouse catalog")
            tables = discover_trino_catalog(
                cursor, catalog=connection.catalog, names=query.tables, include_columns=query.includeFields is not False
            )
            watchdog.check()

    response = DatabaseSchemaQueryResponse(tables={}, joins=[])
    for table in tables:
        name = f"{table.schema}.{table.name}"
        fields: dict[str, DatabaseSchemaField] = {}
        for column in table.columns:
            column_type = trino_column_to_dwh_column(column.name, column.data_type, column.nullable)
            fields[column.name] = DatabaseSchemaField(
                name=column.name,
                hogql_value=quote_hogql_identifier(column.name),
                type=DatabaseSerializedFieldType(column_type["hogql"]),
                schema_valid=True,
            )
        response.tables[name] = DatabaseSchemaDataWarehouseTable(
            id=name, name=name, fields=fields, type="data_warehouse"
        )
    return response
