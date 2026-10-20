from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from posthog.schema import HogQLQuery

from posthog.hogql.escape_sql import escape_trino_identifier, safe_identifier
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.models import Team

from products.managed_warehouse.backend.common import ducklake_data_modeling_schema
from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeTableResult,
    TrinoExpansionMode,
    TrinoIncrementalWrite,
)
from products.managed_warehouse.backend.table_binding import get_data_modeling_table_names
from products.managed_warehouse.backend.trino_compiler import compile_hogql_to_trino_sql
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from trino.dbapi import Cursor

    from posthog.hogql import ast

    from products.managed_warehouse.backend.trino_execution import TrinoQueryControl

STAGE_SUFFIX = "__ph_incremental_stage"

logger = structlog.get_logger(__name__)


class DuplicateUniqueKeyError(ValueError):
    """The incremental rows hold more than one row per unique key, so a merge cannot place them."""


def execute_trino_shadow_materialization(
    *,
    organization_id: str,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
    incremental: TrinoIncrementalWrite | None = None,
    control: TrinoQueryControl | None = None,
) -> DuckLakeTableResult:
    if control:
        control.checkpoint()
    team = Team.objects.get(pk=team_id, organization_id=organization_id)
    hogql_query = HogQLQuery.model_validate(source_query)
    merge = incremental is not None and incremental.since is not None
    compiled = _compile(team, hogql_query, incremental if merge else None)
    if control:
        control.checkpoint()

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
            _run(cursor, control, f"CREATE SCHEMA IF NOT EXISTS {schema}")
            if merge and not _table_exists(cursor, control, connection.catalog, schema_name, table_name):
                # Nothing to merge into, so build the whole table from the unfiltered query.
                merge = False
                compiled = _compile(team, hogql_query, None)
            sql, parameters = convert_pyformat_placeholders(compiled.sql, compiled.values)
            if merge:
                assert incremental is not None
                stage = f"{schema}.{escape_trino_identifier(table_name + STAGE_SUFFIX)}"
                try:
                    row_count, watermark = _merge(cursor, control, table, stage, sql, parameters, incremental)
                finally:
                    _drop_stage(cursor, stage)
                return DuckLakeTableResult(
                    schema_name=schema_name,
                    table_name=table_name,
                    row_count=row_count,
                    watermark=watermark,
                    merged=True,
                )

            # The connector replaces the table atomically, so a failed write preserves the previous shadow.
            row_count = _run(cursor, control, f"CREATE OR REPLACE TABLE {table} AS {sql}", parameters)
            watermark = (
                _max_key(cursor, control, table, incremental.incremental_key) if incremental is not None else None
            )
        finally:
            cursor.close()

    return DuckLakeTableResult(schema_name=schema_name, table_name=table_name, row_count=row_count, watermark=watermark)


def _compile(team: Team, query: HogQLQuery, incremental: TrinoIncrementalWrite | None) -> Any:
    def select_transform(node: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery | ast.SelectSetQuery:
        # Name the columns first, because the incremental filter can wrap the query in a `SELECT *`.
        node = _name_unnamed_columns(team, node)
        if incremental is None:
            return node
        from products.data_modeling.backend.facade.api import (  # noqa: PLC0415 -- the facade loads lazily
            apply_incremental_filter,
        )

        return apply_incremental_filter(node, incremental_key=incremental.incremental_key, since=incremental.since)

    return compile_hogql_to_trino_sql(
        team.pk,
        query,
        team=team,
        bypass_warehouse_access_control=True,
        expansion_mode=TrinoExpansionMode.DJANGO,
        select_transform=select_transform,
    )


def _name_unnamed_columns(
    team: Team, node: ast.SelectQuery | ast.SelectSetQuery
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Give each unnamed output expression the name ClickHouse gives it, such as ``count()``.

    Trino rejects a CREATE TABLE AS statement with an unnamed column. A plain field keeps its column name.
    A ``COLUMNS(...)`` projection stays as is, because only the resolver can expand it.
    """
    from posthog.hogql import ast  # noqa: PLC0415 -- keeps HogQL imports off Django startup
    from posthog.hogql.context import HogQLContext  # noqa: PLC0415
    from posthog.hogql.printer.hogql import HogQLPrinter  # noqa: PLC0415
    from posthog.hogql.resolver_utils import extract_select_queries  # noqa: PLC0415

    printer = HogQLPrinter(context=HogQLContext(team_id=team.pk, team=team))
    for select in extract_select_queries(node):
        select.select = [
            column
            if isinstance(column, ast.Alias | ast.Field | ast.ColumnsExpr)
            else ast.Alias(alias=safe_identifier(printer.visit(column)), expr=column)
            for column in select.select
        ]
    return node


def _merge(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    table: str,
    stage: str,
    sql: str,
    parameters: list[object],
    incremental: TrinoIncrementalWrite,
) -> tuple[int, Any]:
    """Stage the new rows, then merge them into ``table`` on the unique key in one statement.

    Staging first lets the duplicate check and the watermark read the same rows the merge writes,
    and keeps the target untouched until the single MERGE commits.
    """
    staged = _run(cursor, control, f"CREATE OR REPLACE TABLE {stage} AS {sql}", parameters)
    if staged == 0:
        return 0, None

    keys = [escape_trino_identifier(key) for key in incremental.unique_key]
    _run(
        cursor,
        control,
        f"SELECT 1 FROM {stage} GROUP BY {', '.join(keys)} HAVING count(*) > 1 LIMIT 1",
        fetch=False,
    )
    if cursor.fetchall():
        raise DuplicateUniqueKeyError(
            f"The incremental rows hold more than one row per unique key ({', '.join(incremental.unique_key)})"
        )

    _run(cursor, control, f"SELECT * FROM {stage} LIMIT 0")
    columns = [escape_trino_identifier(column[0]) for column in cursor.description or []]
    on = " AND ".join(f"t.{key} = s.{key}" for key in keys)
    updates = ", ".join(f"{column} = s.{column}" for column in columns)
    inserted = ", ".join(columns)
    values = ", ".join(f"s.{column}" for column in columns)
    _run(
        cursor,
        control,
        f"MERGE INTO {table} t USING {stage} s ON {on} "
        f"WHEN MATCHED THEN UPDATE SET {updates} "
        f"WHEN NOT MATCHED THEN INSERT ({inserted}) VALUES ({values})",
    )
    return staged, _max_key(cursor, control, stage, incremental.incremental_key)


def _drop_stage(cursor: Cursor, stage: str) -> None:
    # A leftover stage costs storage only; the next run replaces it. Never mask the build's own error.
    try:
        _run(cursor, None, f"DROP TABLE IF EXISTS {stage}")
    except Exception:
        logger.warning("trino_incremental_stage_drop_failed", stage=stage, exc_info=True)


def _table_exists(
    cursor: Cursor, control: TrinoQueryControl | None, catalog: str, schema_name: str, table_name: str
) -> bool:
    _run(
        cursor,
        control,
        f"SELECT 1 FROM {escape_trino_identifier(catalog)}.information_schema.tables "
        "WHERE table_schema = ? AND table_name = ? AND table_type = 'BASE TABLE'",
        [schema_name, table_name],
        fetch=False,
    )
    return bool(cursor.fetchall())


def _max_key(cursor: Cursor, control: TrinoQueryControl | None, table: str, incremental_key: str) -> Any:
    _run(cursor, control, f"SELECT max({escape_trino_identifier(incremental_key)}) FROM {table}", fetch=False)
    rows = cursor.fetchall()
    return rows[0][0] if rows else None


def _run(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    statement: str,
    parameters: list[object] | None = None,
    *,
    fetch: bool = True,
) -> int:
    """Run one statement and return the row count Trino reports for a write.

    ``fetch=False`` leaves the result for the caller to read.
    """
    if control:
        control.checkpoint()
    if parameters:
        cursor.execute(statement, parameters)
    else:
        cursor.execute(statement)
    if not fetch:
        return -1
    cursor.fetchall()
    row_count = cursor.rowcount
    if statement.startswith(("CREATE OR REPLACE TABLE", "MERGE")) and row_count < 0:
        raise RuntimeError("Trino did not report the materialized row count")
    return row_count
