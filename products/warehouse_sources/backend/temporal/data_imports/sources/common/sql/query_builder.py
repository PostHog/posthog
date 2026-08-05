"""Safe `SELECT` builder shared by every SQL source.

Assembles a read query from already-quoted identifiers (via an
`IdentifierQuoter`) and a value passed through as a driver-native parameter.
Values are **never** interpolated into the SQL string — they only ever leave
this module inside the returned `params` mapping, which the caller passes
straight to the DB cursor (`cursor.execute(sql, params)`).

Supported parameter placeholder styles match the drivers used today:

- `ParamStyle.PYFORMAT_NAMED` — `%(name)s` (psycopg, pymysql, pymssql).
- `ParamStyle.QMARK` — `?` positional (pyodbc/ADO-style).
- `ParamStyle.NUMERIC` — `:1`, `:2` … (snowflake-connector binding=numeric).
- `ParamStyle.NAMED` — `:name` (snowflake `qmark`-style, BigQuery
  parameterized queries).

Every existing hand-rolled `_build_query` in `mysql.py`, `mssql.py`,
`snowflake.py`, `bigquery.py`, `redshift.py`, `clickhouse.py` can be
expressed as a `SelectQueryBuilder` call.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Union

from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import IdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ValidatedRowFilter,
    is_multi_value_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    compute_projected_columns,
    format_projected_select_clause,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class ParamStyle(enum.Enum):
    PYFORMAT_NAMED = "pyformat_named"
    QMARK = "qmark"
    NUMERIC = "numeric"
    NAMED = "named"


@dataclass(frozen=True)
class SafeSQL:
    """A SQL statement that never contains an interpolated value.

    `sql` is the statement text with driver-appropriate placeholders;
    `params` is the mapping (or positional list) the caller hands to the
    cursor. Together they form the only safe way to execute a query
    assembled by this package.
    """

    sql: str
    params: Union[dict[str, Any], list[Any]]


@dataclass(frozen=True)
class SelectQueryBuilder:
    """Builder for a `SELECT * FROM <table> [WHERE ...] [ORDER BY ...]` query.

    `quoter` controls how identifiers are quoted; `param_style` controls how
    parameter placeholders are emitted. Builder instances are frozen so the
    same builder can be reused across calls without risk of accidental state
    leak between sources.
    """

    quoter: IdentifierQuoter
    param_style: ParamStyle = ParamStyle.PYFORMAT_NAMED

    def select_all(
        self,
        *,
        schema: str,
        table_name: str,
        incremental_field: str | None = None,
        incremental_field_type: IncrementalFieldType | None = None,
        incremental_last_value: Any | None = None,
        extra_table_hint: str | None = None,
        order_by_incremental: bool = True,
        enabled_columns: list[str] | None = None,
        primary_keys: list[str] | None = None,
        row_filters: list[ValidatedRowFilter] | None = None,
    ) -> SafeSQL:
        """Build a `SELECT … FROM schema.table` with optional incremental predicate.

        When `incremental_field` is provided, appends
        `WHERE <incremental_field> <op> :last_value [ORDER BY <incremental_field> ASC]`.
        `<op>` is `>=` for `Date` (day-granularity boundary) and `>` for
        every other type — same semantics as `incremental_type_to_operator`.
        `incremental_last_value` falls back to the type's initial value so
        the semantics match today's `_build_query` implementations.

        `enabled_columns=None` (default) emits `SELECT *`. Otherwise projects to listed columns;
        PKs + active incremental field always retained. See `compute_projected_columns`.

        `row_filters` are ANDed onto the `WHERE` clause as `<col> <op> <value>`
        conditions. The value is always emitted as a bound parameter, never
        interpolated. Filters compose with the incremental predicate (both ANDed).

        `extra_table_hint` is appended verbatim after the table reference
        (e.g. MySQL `FORCE INDEX (...)`). Callers who use it must have
        already validated it through their quoter — the builder itself
        does not parse hint syntax.
        """
        table_ref = self.quoter.quote_qualified(schema, table_name)
        hint = f" {extra_table_hint}" if extra_table_hint else ""

        projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
        select_clause = format_projected_select_clause(projected, self.quoter)

        params = self._empty_params()
        conditions: list[str] = []
        quoted_incremental_field: str | None = None

        if incremental_field is not None:
            if incremental_field_type is None:
                raise ValueError("incremental_field_type is required when incremental_field is set")
            value = (
                incremental_last_value
                if incremental_last_value is not None
                else incremental_type_to_initial_value(incremental_field_type)
            )
            quoted_incremental_field = self.quoter.quote(incremental_field)
            placeholder = self._append_param("incremental_value", value, params)
            operator = incremental_type_to_operator(incremental_field_type)
            conditions.append(f"{quoted_incremental_field} {operator} {placeholder}")

        for index, row_filter in enumerate(row_filters or []):
            quoted_column = self.quoter.quote(row_filter.column)
            if is_multi_value_operator(row_filter.operator):
                placeholders = [
                    self._append_param(f"row_filter_{index}_{position}", element, params)
                    for position, element in enumerate(row_filter.value)
                ]
                conditions.append(f"{quoted_column} {row_filter.operator} ({', '.join(placeholders)})")
            else:
                placeholder = self._append_param(f"row_filter_{index}", row_filter.value, params)
                conditions.append(f"{quoted_column} {row_filter.operator} {placeholder}")

        parts = [f"SELECT {select_clause} FROM {table_ref}{hint}"]
        if conditions:
            parts.append("WHERE " + " AND ".join(conditions))
        if quoted_incremental_field is not None and order_by_incremental:
            parts.append(f"ORDER BY {quoted_incremental_field} ASC")

        return SafeSQL(sql=" ".join(parts), params=params)

    def _empty_params(self) -> dict[str, Any] | list[Any]:
        if self.param_style in (ParamStyle.PYFORMAT_NAMED, ParamStyle.NAMED):
            return {}
        return []

    def _append_param(self, name: str, value: Any, params: dict[str, Any] | list[Any]) -> str:
        """Add a value to `params` and return the placeholder that references it.

        Positional styles (`QMARK`, `NUMERIC`) index by current list length, so
        callers must add params in the same order the placeholders appear in the SQL.
        """
        if self.param_style == ParamStyle.PYFORMAT_NAMED:
            assert isinstance(params, dict)
            params[name] = value
            return f"%({name})s"
        if self.param_style == ParamStyle.NAMED:
            assert isinstance(params, dict)
            params[name] = value
            return f":{name}"
        if self.param_style == ParamStyle.QMARK:
            assert isinstance(params, list)
            params.append(value)
            return "?"
        if self.param_style == ParamStyle.NUMERIC:
            assert isinstance(params, list)
            params.append(value)
            return f":{len(params)}"
        raise ValueError(f"Unsupported param style: {self.param_style}")
