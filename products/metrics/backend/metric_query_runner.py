"""Single-metric time-series query runner.

Returns a list of `(time_bucket, value)` points for one metric over a date
range, with a choice of aggregation. Modelled after the logs
`SparklineQueryRunner` shape but flattened — we don't yet need the full
`AnalyticsQueryRunner[LogsQueryResponse]` infrastructure since this product
isn't going through HogQL `DataNode` caching, schema-gen or the data-viz
pipeline yet.
"""

import datetime as dt
from typing import Any, Literal

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

AttributeScope = Literal["resource", "attribute", "auto"]

_ALLOWED_ATTRIBUTE_SCOPES: frozenset[str] = frozenset({"resource", "attribute", "auto"})


def attribute_field(name: str, *, scope: AttributeScope = "auto") -> ast.Expr:
    """Build the HogQL AST node that accesses a metric attribute by name.

    This is the single seam between the upcoming filter / group-by / rate /
    histogram-quantile work (PR3-PR6) and the underlying `metrics1` storage
    shape. When the Snuffle-style streams-table rewrite lands, only this
    function changes — every call site keeps working.

    `scope` resolves *where* the attribute lives:

    - ``"resource"`` — look in ``resource_attributes`` only (Prometheus-style
      `service.name`, `k8s.pod.name` — set once per scrape target).
    - ``"attribute"`` — look in ``attributes`` only (the alias view of
      ``attributes_map_str`` that strips the 5-char ``__str`` type tag from
      each key). Per-data-point labels like ``http.method`` live here.
    - ``"auto"`` (default) — try resource first, fall back to attribute if
      empty. Map lookups in ClickHouse return ``''`` for missing keys, not
      NULL, so the fallback compares against the empty string.

    The empty-string fallback is documented behaviour, not a bug: it means
    callers cannot meaningfully filter for "attribute equals empty string"
    in auto scope. Use an explicit scope for that edge case.
    """
    if scope not in _ALLOWED_ATTRIBUTE_SCOPES:
        raise ValueError(f"Unknown attribute scope: {scope!r}")

    name_constant = ast.Constant(value=name)

    # arrayElement, not subscript: HogQL prints `field[...]` on a
    # StringJSONDatabaseField as JSONExtractRaw, which is illegal on the
    # physical Map columns. arrayElement passes through and is ClickHouse's
    # native Map accessor ('' for missing keys).
    if scope == "resource":
        return parse_expr("arrayElement(resource_attributes, {name})", placeholders={"name": name_constant})
    if scope == "attribute":
        return parse_expr("arrayElement(attributes, {name})", placeholders={"name": name_constant})
    return parse_expr(
        "if(arrayElement(resource_attributes, {name}) != '', arrayElement(resource_attributes, {name}), arrayElement(attributes, {name}))",
        placeholders={"name": name_constant},
    )


def _aggregation_expr(name: str) -> ast.Expr:
    """Build the HogQL AST for the supported aggregations.

    Kept as AST nodes (rather than string interpolation) so the
    `hogql-no-fstring` semgrep rule doesn't have to special-case this
    runner — the function name and percentile literal travel as a
    typed expression, not as substituted text.
    """
    value_field = ast.Field(chain=["value"])
    if name == "sum":
        return ast.Call(name="sum", args=[value_field])
    if name == "avg":
        return ast.Call(name="avg", args=[value_field])
    if name == "count":
        return ast.Call(name="count", args=[])
    if name == "p95":
        return ast.Call(name="quantile", params=[ast.Constant(value=0.95)], args=[value_field])
    raise ValueError(f"Unsupported aggregation: {name!r}")


_ALLOWED_AGGREGATIONS: frozenset[str] = frozenset({"sum", "avg", "count", "p95"})

# Target ~60 buckets across the requested range — feels right for a chart.
_TARGET_BUCKET_COUNT = 60

# Order from finest to coarsest. The first interval that yields
# <= _TARGET_BUCKET_COUNT buckets wins.
_INTERVAL_LADDER: list[tuple[str, dt.timedelta, ast.Call]] = [
    ("second", dt.timedelta(seconds=1), ast.Call(name="toIntervalSecond", args=[ast.Constant(value=1)])),
    ("minute", dt.timedelta(minutes=1), ast.Call(name="toIntervalMinute", args=[ast.Constant(value=1)])),
    ("minute_5", dt.timedelta(minutes=5), ast.Call(name="toIntervalMinute", args=[ast.Constant(value=5)])),
    ("minute_15", dt.timedelta(minutes=15), ast.Call(name="toIntervalMinute", args=[ast.Constant(value=15)])),
    ("hour", dt.timedelta(hours=1), ast.Call(name="toIntervalHour", args=[ast.Constant(value=1)])),
    ("hour_6", dt.timedelta(hours=6), ast.Call(name="toIntervalHour", args=[ast.Constant(value=6)])),
    ("day", dt.timedelta(days=1), ast.Call(name="toIntervalDay", args=[ast.Constant(value=1)])),
    ("week", dt.timedelta(weeks=1), ast.Call(name="toIntervalWeek", args=[ast.Constant(value=1)])),
]


def _pick_interval(date_from: dt.datetime, date_to: dt.datetime) -> str:
    """Pick the finest interval that keeps bucket count at or below the target."""
    span = date_to - date_from
    for name, step, _ in _INTERVAL_LADDER:
        if span / step <= _TARGET_BUCKET_COUNT:
            return name
    return _INTERVAL_LADDER[-1][0]


def _interval_expr(name: str) -> ast.Call:
    for entry_name, _, expr in _INTERVAL_LADDER:
        if entry_name == name:
            return expr
    raise ValueError(f"Unknown interval: {name!r}")


class MetricQueryRunner:
    def __init__(
        self,
        team: Team,
        metric_name: str,
        aggregation: str,
        date_from: dt.datetime,
        date_to: dt.datetime,
    ) -> None:
        if aggregation not in _ALLOWED_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation: {aggregation!r}")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")

        self.team = team
        self.metric_name = metric_name
        self.aggregation = aggregation
        self.date_from = date_from
        self.date_to = date_to
        self.interval = _pick_interval(date_from, date_to)

    def run(self) -> list[dict[str, Any]]:
        # `metrics` is only registered under the `posthog.` HogQL namespace
        # (see posthog/hogql/database/database.py).
        query = parse_select(
            """
                SELECT
                    toStartOfInterval(timestamp, {interval}) AS time,
                    {aggregation} AS value
                FROM posthog.metrics
                WHERE metric_name = {metric_name}
                  AND timestamp >= {date_from}
                  AND timestamp < {date_to}
                GROUP BY time
                ORDER BY time ASC
                LIMIT 10000
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "aggregation": _aggregation_expr(self.aggregation),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        return [
            {"time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0], "value": row[1]}
            for row in response.results
        ]
