"""psycopg rendering of row-filter predicates for Postgres / Redshift.

Separate from `predicates.py` so the psycopg import stays off the serializer path.

Values are `sql.Literal` (psycopg adapts them server-side, never interpolated),
columns are `sql.Identifier`, and the operator is already canonical so `sql.SQL` is safe.
"""

from __future__ import annotations

from psycopg import sql

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ValidatedRowFilter,
    is_multi_value_operator,
)


def _render_one(row_filter: ValidatedRowFilter) -> sql.Composable:
    col = sql.Identifier(row_filter.column)
    op = sql.SQL(row_filter.operator)
    if is_multi_value_operator(row_filter.operator):
        # `<col> IN (lit, lit, ...)` — each element is a psycopg-adapted literal.
        values = sql.SQL(", ").join(sql.Literal(element) for element in row_filter.value)
        return sql.SQL("{col} {op} ({vals})").format(col=col, op=op, vals=values)
    return sql.SQL("{col} {op} {val}").format(col=col, op=op, val=sql.Literal(row_filter.value))


def render_psycopg_row_filter_conditions(filters: list[ValidatedRowFilter]) -> list[sql.Composable]:
    """Render each row filter as a psycopg composable (`<col> <op> <literal>`, or
    `<col> IN (<literal>, ...)` for multi-value operators)."""
    return [_render_one(row_filter) for row_filter in filters]


def and_join(conditions: list[sql.Composable]) -> sql.Composable:
    """AND-join a list of composable conditions into one composable."""
    return sql.SQL(" AND ").join(conditions)
