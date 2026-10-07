"""Run a SQL metrics insight.

A SQL metrics insight is a HogQL SELECT over the metrics tables. It runs on the metrics query path,
not as a generic SQL insight: the metrics runner caches it, the logs workload runs it, and the
metrics byte cap limits it. To keep those limits honest, it may read only the metrics tables.

The result contract: a `time` column, a numeric `value` column, and any other columns as series
labels. The SQL can use `{date_from}`, `{date_to}`, `{interval}` and `{interval_seconds}`, filled in
from the insight's (or dashboard's) date range and the bucket interval.
"""

import math
import datetime as dt
from typing import Any

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.metrics import (
    MetricAttributesTable,
    MetricNamesTable,
    MetricSamplesTable,
    MetricSeriesTable,
    MetricsTable,
)
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries
from products.metrics.backend.metric_query_runner import (
    _QUERY_SETTINGS,
    _ROW_LIMIT,
    _align_to_interval,
    _interval_expr,
    _interval_step,
    _resolve_interval,
)
from products.metrics.backend.series import rank_and_fill_series

METRICS_SQL_TABLES: frozenset[str] = frozenset(
    {"metrics", "metric_samples", "metric_series", "metric_names", "metric_attributes"}
)

# The same label as a PromQL `clause` label: it names the series of a multi-series query.
CLAUSE_COLUMN = "clause"


# A FROM source that reads no table itself: its own FROM clauses are checked where they appear.
_SUBQUERY_TYPES = (
    ast.SelectQueryType,
    ast.SelectSetQueryType,
    ast.SelectQueryAliasType,
    ast.CTETableType,
    ast.CTETableAliasType,
)
_METRICS_TABLE_CLASSES: tuple[type[Table], ...] = (
    MetricsTable,
    MetricSamplesTable,
    MetricNamesTable,
    MetricSeriesTable,
    MetricAttributesTable,
)


class _TableCollector(TraversingVisitor):
    """Collects every FROM and JOIN source of a resolved query that is not a metrics table.

    It reads the resolved types, not the raw AST: the resolver applies the CTE scope rules and
    expands HogQLX tags, so a CTE name or a tag cannot hide another table.
    """

    def __init__(self) -> None:
        self.other_tables: list[str] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        table_type = node.type
        while isinstance(table_type, ast.TableAliasType):
            table_type = table_type.table_type
        if not isinstance(table_type, _SUBQUERY_TYPES) and not (
            isinstance(table_type, ast.TableType) and isinstance(table_type.table, _METRICS_TABLE_CLASSES)
        ):
            name = ".".join(str(part) for part in node.table.chain) if isinstance(node.table, ast.Field) else None
            self.other_tables.append(name or "a table that is not a metrics table")
        super().visit_join_expr(node)


def _assert_reads_only_metrics_tables(team: Team, query: ast.SelectQuery | ast.SelectSetQuery) -> None:
    context = HogQLContext(
        team_id=team.pk, team=team, database=Database.create_for(team=team), enable_select_queries=True
    )
    collector = _TableCollector()
    collector.visit(resolve_types(query, context, dialect="clickhouse"))
    if collector.other_tables:
        raise ExposedHogQLError(
            f"A SQL metrics insight can only read the metrics tables "
            f"({', '.join(f'posthog.{table}' for table in sorted(METRICS_SQL_TABLES))}), "
            f"not {collector.other_tables[0]}."
        )


def build_metrics_sql_query(
    team: Team, sql: str, date_from: dt.datetime, date_to: dt.datetime, interval: str | None
) -> ast.SelectQuery:
    """Parse the insight's SQL with the date placeholders filled in, wrapped in the row limit."""
    resolved = _resolve_interval(date_from, date_to, interval)
    step = _interval_step(resolved)
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=_align_to_interval(date_from, resolved, tzinfo=team.timezone_info)),
        "date_to": ast.Constant(value=date_to),
        "interval": _interval_expr(resolved),
        "interval_seconds": ast.Constant(value=int(step.total_seconds())),
    }
    inner = parse_select(sql, placeholders=placeholders)
    _assert_reads_only_metrics_tables(team, inner)
    wrapped = parse_select(
        "SELECT * FROM {inner} LIMIT {row_limit}",
        placeholders={"inner": inner, "row_limit": ast.Constant(value=_ROW_LIMIT)},
    )
    assert isinstance(wrapped, ast.SelectQuery)
    return wrapped


def _time_text(value: Any) -> str:
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def _numeric(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ExposedHogQLError(f'The "value" column must be a number, not {value!r}.')
    return number if math.isfinite(number) else None


def run_metrics_sql(
    team: Team, sql: str, date_from: dt.datetime, date_to: dt.datetime, interval: str | None
) -> list[MetricSeries]:
    query = build_metrics_sql_query(team, sql, date_from, date_to, interval)
    response = execute_hogql_query(
        query_type="MetricsSQLQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_QUERY_SETTINGS,
    )
    columns = [str(column) for column in response.columns or []]
    lowered = [column.lower() for column in columns]
    if "time" not in lowered or "value" not in lowered:
        raise ExposedHogQLError(
            f'A SQL metrics insight must return a "time" and a "value" column. It returned: {", ".join(columns)}.'
        )
    results = response.results or []
    if len(results) >= _ROW_LIMIT:
        raise ExposedHogQLError(
            "The query returned too many rows. Use a coarser interval, a shorter date range, or fewer labels."
        )

    time_index = lowered.index("time")
    value_index = lowered.index("value")
    clause_index = lowered.index(CLAUSE_COLUMN) if CLAUSE_COLUMN in lowered else None
    label_indexes = [index for index in range(len(columns)) if index not in (time_index, value_index, clause_index)]

    points_by_series: dict[tuple[str | None, tuple[tuple[str, str], ...]], list[MetricPoint]] = {}
    for row in results:
        labels = tuple((columns[index], "" if row[index] is None else str(row[index])) for index in label_indexes)
        clause = str(row[clause_index]) if clause_index is not None else None
        points_by_series.setdefault((clause, labels), []).append(
            MetricPoint(time=_time_text(row[time_index]), value=_numeric(row[value_index]))
        )
    return rank_and_fill_series(
        [
            (dict(labels), None, clause, sorted(points, key=lambda point: point.time))
            for (clause, labels), points in points_by_series.items()
        ]
    )
