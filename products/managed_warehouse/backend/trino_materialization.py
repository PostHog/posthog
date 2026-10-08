from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from posthog.schema import HogQLQuery

from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.models import Team

from products.managed_warehouse.backend.common import ducklake_data_modeling_schema
from products.managed_warehouse.backend.facade.contracts import DuckLakeTableResult, TrinoExpansionMode
from products.managed_warehouse.backend.table_binding import get_data_modeling_table_names
from products.managed_warehouse.backend.trino_compiler import compile_hogql_to_trino_sql
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from products.managed_warehouse.backend.trino_execution import TrinoQueryControl


def execute_trino_shadow_materialization(
    *,
    organization_id: str,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
    control: TrinoQueryControl | None = None,
) -> DuckLakeTableResult:
    if control:
        control.checkpoint()
    team = Team.objects.get(pk=team_id, organization_id=organization_id)
    compiled = compile_hogql_to_trino_sql(
        team_id,
        HogQLQuery.model_validate(source_query),
        team=team,
        bypass_warehouse_access_control=True,
        expansion_mode=TrinoExpansionMode.DJANGO,
    )
    if control:
        control.checkpoint()

    sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
    schema_name = ducklake_data_modeling_schema(team_id)
    query_id = UUID(str(saved_query_id))
    table_name = get_data_modeling_table_names(team_id, [query_id])[query_id]
    with connect_managed_warehouse_trino(
        organization_id, principal=f"posthog:trino-materialization:team:{team_id}:view:{saved_query_id}"
    ) as connection:
        schema = f"{escape_trino_identifier(connection.catalog)}.{escape_trino_identifier(schema_name)}"
        table = f"{schema}.{escape_trino_identifier(table_name)}"
        cursor = connection.cursor()
        if control:
            control.attach(cursor)
        try:
            if control:
                control.checkpoint()
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cursor.fetchall()
            if control:
                control.checkpoint()
            # The connector replaces the table atomically, so a failed write preserves the previous shadow.
            cursor.execute(f"CREATE OR REPLACE TABLE {table} AS {sql}", parameters or None)
            cursor.fetchall()
            row_count = cursor.rowcount
            if row_count < 0:
                raise RuntimeError("Trino did not report the materialized row count")
        finally:
            cursor.close()

    return DuckLakeTableResult(schema_name=schema_name, table_name=table_name, row_count=row_count)
