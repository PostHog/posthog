from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from posthog.schema import HogQLQuery

from posthog.hogql.escape_sql import escape_trino_identifier
from posthog.hogql.trino_parameters import convert_pyformat_placeholders

from posthog.models import Team

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES
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
        allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        expansion_mode=TrinoExpansionMode.DJANGO,
        select_transform=select_transform,
        preserve_clickhouse_output_names=True,
    )


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
    if _fetch(cursor, control, f"SELECT 1 FROM {stage} GROUP BY {', '.join(keys)} HAVING count(*) > 1 LIMIT 1"):
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
    rows = _fetch(
        cursor,
        control,
        f"SELECT 1 FROM {escape_trino_identifier(catalog)}.information_schema.tables "
        "WHERE table_schema = ? AND table_name = ? AND table_type = 'BASE TABLE'",
        [schema_name, table_name],
    )
    return bool(rows)


def _max_key(cursor: Cursor, control: TrinoQueryControl | None, table: str, incremental_key: str) -> Any:
    rows = _fetch(cursor, control, f"SELECT max({escape_trino_identifier(incremental_key)}) FROM {table}")
    return rows[0][0] if rows else None


def _run(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    statement: str,
    parameters: list[object] | None = None,
) -> int:
    """Run one statement and return the row count Trino reports for a write."""
    _fetch(cursor, control, statement, parameters)
    row_count = cursor.rowcount
    if statement.startswith(("CREATE OR REPLACE TABLE", "MERGE")) and row_count < 0:
        raise RuntimeError("Trino did not report the materialized row count")
    return row_count


def _fetch(
    cursor: Cursor,
    control: TrinoQueryControl | None,
    statement: str,
    parameters: list[object] | None = None,
) -> list[Any]:
    """Run one statement, read all of its rows, and report the bytes it processed to ``control``."""
    if control:
        control.checkpoint()
    stats_before = cursor.stats
    try:
        if parameters:
            cursor.execute(statement, parameters)
        else:
            cursor.execute(statement)
        return cursor.fetchall()
    finally:
        # The client updates the statistics with every response, so they are final once the rows are read.
        # A failed statement reports what it processed as of the last response before the error: the client
        # raises on the error response before it reads that response's statistics, so the figure is a lower bound.
        # When ``execute`` fails before it starts a query, the cursor still holds the previous statement's
        # statistics, which are already counted.
        stats = cursor.stats
        if control is not None and stats is not None and stats is not stats_before:
            control.record_processed_bytes(stats.get("processedBytes"))
