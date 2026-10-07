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
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
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


class _TableCollector(TraversingVisitor):
    """Collects every table a query reads, so a SQL metrics insight cannot read other data."""

    def __init__(self) -> None:
        self.tables: list[list[str | int]] = []
        self.cte_names: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.cte_names.update((node.ctes or {}).keys())
        super().visit_select_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.tables.append(node.table.chain)
        super().visit_join_expr(node)


def _assert_reads_only_metrics_tables(query: ast.SelectQuery | ast.SelectSetQuery) -> None:
    collector = _TableCollector()
    collector.visit(query)
    for chain in collector.tables:
        name = ".".join(str(part) for part in chain)
        if len(chain) == 1 and chain[0] in collector.cte_names:
            continue
        if len(chain) == 2 and chain[0] == "posthog" and chain[1] in METRICS_SQL_TABLES:
            continue
        raise ExposedHogQLError(
            f"A SQL metrics insight can only read the metrics tables "
            f"({', '.join(f'posthog.{table}' for table in sorted(METRICS_SQL_TABLES))}), not {name}."
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
    _assert_reads_only_metrics_tables(inner)
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
