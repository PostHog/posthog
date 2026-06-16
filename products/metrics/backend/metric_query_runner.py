"""Single-metric time-series query runner.

Returns a list of `(time_bucket, value)` points for one metric over a date
range, with a choice of aggregation. Modelled after the logs
`SparklineQueryRunner` shape but flattened — we don't yet need the full
`AnalyticsQueryRunner[LogsQueryResponse]` infrastructure since this product
isn't going through HogQL `DataNode` caching, schema-gen or the data-viz
pipeline yet.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy
from products.metrics.backend.facade.enums import FilterOp

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


_ALLOWED_AGGREGATIONS: frozenset[str] = frozenset({"sum", "avg", "count", "p95", "rate", "increase"})

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


def _filter_condition(filter: MetricFilter) -> ast.Expr:
    """One label predicate as a HogQL boolean expression.

    Missing map keys resolve to `''`, so `neq`/`not_regex` also match rows
    that lack the key entirely — same as Prometheus negative matchers.
    """
    field = attribute_field(filter.key, scope=filter.scope.value)
    placeholders: dict[str, ast.Expr] = {"field": field, "value": ast.Constant(value=filter.value)}
    if filter.op == FilterOp.EQ:
        return parse_expr("{field} = {value}", placeholders=placeholders)
    if filter.op == FilterOp.NEQ:
        return parse_expr("{field} != {value}", placeholders=placeholders)
    if filter.op == FilterOp.REGEX:
        return parse_expr("match({field}, {value})", placeholders=placeholders)
    if filter.op == FilterOp.NOT_REGEX:
        return parse_expr("not match({field}, {value})", placeholders=placeholders)
    raise ValueError(f"Unsupported filter op: {filter.op!r}")


def _filters_expr(filters: Sequence[MetricFilter]) -> ast.Expr:
    """AND of all filter conditions; TRUE when there are none."""
    if not filters:
        return ast.Constant(value=True)
    conditions = [_filter_condition(f) for f in filters]
    if len(conditions) == 1:
        return conditions[0]
    return ast.And(exprs=conditions)


class MetricQueryRunner:
    def __init__(
        self,
        team: Team,
        metric_name: str,
        aggregation: str,
        date_from: dt.datetime,
        date_to: dt.datetime,
        filters: Sequence[MetricFilter] = (),
        group_by: Sequence[MetricGroupBy] = (),
        interval: str | None = None,
    ) -> None:
        if aggregation not in _ALLOWED_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation: {aggregation!r}")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if interval is not None and interval not in {name for name, _, _ in _INTERVAL_LADDER}:
            raise ValueError(f"Unknown interval: {interval!r}")

        self.team = team
        self.metric_name = metric_name
        self.aggregation = aggregation
        self.date_from = date_from
        self.date_to = date_to
        self.filters = tuple(filters)
        self.group_by = tuple(group_by)
        self.interval = interval or _pick_interval(date_from, date_to)

    def run(self) -> list[dict[str, Any]]:
        """Bucketed rows: `{"time", "value", "labels"}`. `labels` carries one
        entry per group_by key (always `{}` without group_by)."""
        if self.aggregation in ("rate", "increase"):
            query = self._build_counter_query()
        else:
            query = self._build_simple_query()

        response = execute_hogql_query(
            query_type="MetricQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        group_count = len(self.group_by)
        rows: list[dict[str, Any]] = []
        for row in response.results:
            rows.append(
                {
                    "time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0],
                    "value": row[1 + group_count],
                    "labels": {group.key: row[1 + index] for index, group in enumerate(self.group_by)},
                }
            )
        return rows

    def _splice_group_columns(self, query: ast.SelectQuery) -> None:
        """Insert the group_by label columns between `time` and `value` —
        parse_select placeholders can't express a variable column count."""
        assert query.group_by is not None
        for index, group in enumerate(self.group_by):
            label_expr = ast.Call(name="toString", args=[attribute_field(group.key, scope=group.scope.value)])
            query.select.insert(1 + index, ast.Alias(alias=f"group_{index}", expr=label_expr))
            query.group_by.append(ast.Field(chain=[f"group_{index}"]))

    def _build_simple_query(self) -> ast.SelectQuery:
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
                  AND {filters}
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
                "filters": _filters_expr(self.filters),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query

    def _build_counter_query(self) -> ast.SelectQuery:
        """rate/increase: per-underlying-series deltas, then aggregate.

        Each physical series (service_name, resource_fingerprint, datapoint
        attributes) gets its samples diffed in timestamp order via a window
        function, Prometheus-style:

        - cumulative temporality: contribution = value - prev, clamped for
          counter resets (value < prev means the counter restarted, so the
          post-reset absolute value IS the increase); the first sample of a
          series contributes 0 (its history is unknown).
        - delta temporality: each sample already is the increase, so it
          contributes its own value.

        `increase` sums contributions per bucket; `rate` divides by the
        bucket length in seconds.
        """
        step_seconds = next(step.total_seconds() for name, step, _ in _INTERVAL_LADDER if name == self.interval)
        divisor = step_seconds if self.aggregation == "rate" else 1.0
        query = parse_select(
            """
                SELECT
                    toStartOfInterval(sample_timestamp, {interval}) AS time,
                    sum(contribution) / {divisor} AS value
                FROM (
                    SELECT
                        timestamp AS sample_timestamp,
                        attributes AS attributes,
                        resource_attributes AS resource_attributes,
                        multiIf(
                            aggregation_temporality = 'delta', value,
                            isNull(prev_value), 0.0,
                            value >= assumeNotNull(prev_value), value - assumeNotNull(prev_value),
                            value
                        ) AS contribution
                    FROM (
                        SELECT
                            timestamp,
                            value,
                            aggregation_temporality,
                            attributes,
                            resource_attributes,
                            lagInFrame(toNullable(value)) OVER (
                                PARTITION BY service_name, resource_fingerprint, toString(attributes)
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_value
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND timestamp >= {date_from}
                          AND timestamp < {date_to}
                          AND {filters}
                    )
                )
                GROUP BY time
                ORDER BY time ASC
                LIMIT 10000
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "divisor": ast.Constant(value=divisor),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": _filters_expr(self.filters),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query
