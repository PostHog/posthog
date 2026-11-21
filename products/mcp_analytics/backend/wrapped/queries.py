"""The two ClickHouse reads behind MCP Wrapped: a cheap monthly count and one pass over the period's tool calls.

Every MCP property lives inside `properties`, so reading that column is what costs. The aggregate query reads
it once and ARRAY JOINs each call into every dimension a card needs, rather than scanning once per dimension.
Tool, harness and lab are computed with the dashboard's own expressions, so the two count the same way.
"""

import math
from collections.abc import Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from posthog.schema import HogQLFilters

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.team import Team

from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.custom_harnesses import custom_harness_rules
from products.mcp_analytics.backend.hogql_queries.base import EFFECTIVE_TOOL_SQL
from products.mcp_analytics.backend.hogql_queries.dashboard_query import lab_expr
from products.mcp_analytics.backend.mcp_harness import HARNESS_TOKEN_SQL, harness_label_sql
from products.mcp_analytics.backend.wrapped.model_families import model_family_expr

# Generous because no one waits on this batch job. The cap only stops a runaway scan.
MAX_EXECUTION_TIME_SECONDS = 600
# Far above any card's needs. Tools are the only dimension that can grow this long.
ROWS_PER_DIMENSION = 500


class Dimension(StrEnum):
    TOTAL = "total"
    TOOL = "tool"
    HARNESS = "harness"
    LAB = "lab"
    MODEL_FAMILY = "model_family"
    SERVER = "server"
    MONTH = "month"
    WEEK_HOUR = "week_hour"


@frozen
class WrappedPeriod:
    year: int
    # Midnight on Jan 1 to midnight on Dec 1 in the project's timezone, end exclusive.
    start: datetime
    end: datetime

    @classmethod
    def for_year(cls, team: Team, year: int) -> "WrappedPeriod":
        tz = team.timezone_info
        return cls(year=year, start=datetime(year, 1, 1, tzinfo=tz), end=datetime(year, 12, 1, tzinfo=tz))


@frozen
class MonthCalls:
    month: date
    calls: int


@frozen
class DimensionRow:
    key: str
    calls: int
    errors: int
    p95_duration_ms: float | None
    calls_without_duration: int


@frozen
class WrappedAggregates:
    total: DimensionRow
    tools: tuple[DimensionRow, ...]
    harnesses: tuple[DimensionRow, ...]
    labs: tuple[DimensionRow, ...]
    model_families: tuple[DimensionRow, ...]
    servers: tuple[DimensionRow, ...]
    months: tuple[DimensionRow, ...]
    week_hours: tuple[DimensionRow, ...]


_MONTHLY_CALLS_SQL = """
SELECT toStartOfMonth(timestamp) AS month, count() AS calls
FROM events
WHERE event = {event} AND timestamp >= {start} AND timestamp < {end}
GROUP BY month
ORDER BY month
LIMIT 24
"""

_AGGREGATES_SQL = """
SELECT
    kind,
    key,
    count() AS calls,
    countIf(is_error) AS errors,
    quantile(0.95)(duration_ms) AS p95_duration_ms,
    countIf(isNull(duration_ms)) AS calls_without_duration
FROM (
    SELECT tool, {harness_label} AS harness, lab, model_family, server, month, week_hour, is_error, duration_ms
    FROM (
        SELECT
            {tool} AS tool,
            {harness_token} AS h,
            {lab} AS lab,
            {model_family} AS model_family,
            coalesce(toString(properties.$mcp_server_name), '') AS server,
            toString(toStartOfMonth(timestamp)) AS month,
            toString(toDayOfWeek(timestamp) * 100 + toHour(timestamp)) AS week_hour,
            coalesce(toBool(properties.$mcp_is_error), false) AS is_error,
            toFloat(properties.$mcp_duration_ms) AS duration_ms
        FROM events
        WHERE event = {event}
            AND timestamp >= {start}
            AND timestamp < {end}
            AND properties.$mcp_tool_name IS NOT NULL
            AND properties.$mcp_tool_name != ''
            AND {filters}
    )
)
ARRAY JOIN
    {kinds} AS kind,
    ['', tool, harness, lab, model_family, server, month, week_hour] AS key
GROUP BY kind, key
ORDER BY kind, calls DESC, key
LIMIT {rows_per_dimension} BY kind
LIMIT 10000
"""

# Order matches the key array in _AGGREGATES_SQL.
_KINDS = (
    Dimension.TOTAL,
    Dimension.TOOL,
    Dimension.HARNESS,
    Dimension.LAB,
    Dimension.MODEL_FAMILY,
    Dimension.SERVER,
    Dimension.MONTH,
    Dimension.WEEK_HOUR,
)


def _period_placeholders(period: WrappedPeriod) -> dict[str, ast.Expr]:
    return {
        "event": ast.Constant(value=MCP_TOOL_CALL_EVENT),
        "start": ast.Constant(value=period.start),
        "end": ast.Constant(value=period.end),
    }


def _run(team: Team, sql: str, placeholders: dict[str, ast.Expr], name: str, filters: HogQLFilters | None) -> list[Any]:
    with tags_context(product=Product.MCP_ANALYTICS, feature=Feature.DIGEST, team_id=team.pk, name=name):
        response = execute_hogql_query(
            query=sql,
            team=team,
            placeholders=placeholders,
            filters=filters,
            # A yearly batch job. Nobody waits on screen for it.
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME_SECONDS, timeout_overflow_mode="throw"),
        )
    return response.results or []


def fetch_monthly_calls(team: Team, period: WrappedPeriod) -> tuple[MonthCalls, ...]:
    """Calls per month from timestamps alone, cheap enough to run before deciding a project is eligible."""
    rows = _run(team, _MONTHLY_CALLS_SQL, _period_placeholders(period), "mcp_wrapped_monthly_calls", filters=None)
    return tuple(MonthCalls(month=_as_date(row[0]), calls=int(row[1])) for row in rows)


def fetch_wrapped_aggregates(team: Team, period: WrappedPeriod) -> WrappedAggregates:
    placeholders = {
        **_period_placeholders(period),
        "tool": parse_expr(EFFECTIVE_TOOL_SQL),
        "harness_token": parse_expr(HARNESS_TOKEN_SQL),
        "harness_label": parse_expr(harness_label_sql("h", custom_harness_rules(team))),
        "lab": lab_expr(),
        "model_family": model_family_expr(),
        "kinds": ast.Array(exprs=[ast.Constant(value=str(kind)) for kind in _KINDS]),
        "rows_per_dimension": ast.Constant(value=ROWS_PER_DIMENSION),
    }
    # The dashboard applies the project's test account filters by default, so the wrap does too.
    filters = HogQLFilters(filterTestAccounts=bool(team.test_account_filters_default_checked))
    rows = _run(team, _AGGREGATES_SQL, placeholders, "mcp_wrapped_aggregates", filters=filters)
    return _aggregates_from_rows(rows)


def _aggregates_from_rows(rows: Sequence[Sequence[Any]]) -> WrappedAggregates:
    by_kind: dict[str, list[DimensionRow]] = {str(kind): [] for kind in Dimension}
    for kind, key, calls, errors, p95, without_duration in rows:
        by_kind[kind].append(
            DimensionRow(
                key=str(key),
                calls=int(calls),
                errors=int(errors),
                # The p95 ends up in a Postgres jsonb payload, which cannot store NaN or infinity.
                p95_duration_ms=float(p95) if p95 is not None and math.isfinite(p95) else None,
                calls_without_duration=int(without_duration),
            )
        )
    totals = by_kind[Dimension.TOTAL]
    total = (
        totals[0] if totals else DimensionRow(key="", calls=0, errors=0, p95_duration_ms=None, calls_without_duration=0)
    )
    return WrappedAggregates(
        total=total,
        tools=tuple(by_kind[Dimension.TOOL]),
        harnesses=tuple(by_kind[Dimension.HARNESS]),
        labs=tuple(by_kind[Dimension.LAB]),
        model_families=tuple(by_kind[Dimension.MODEL_FAMILY]),
        servers=tuple(by_kind[Dimension.SERVER]),
        months=tuple(sorted(by_kind[Dimension.MONTH], key=lambda row: row.key)),
        week_hours=tuple(by_kind[Dimension.WEEK_HOUR]),
    )


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
