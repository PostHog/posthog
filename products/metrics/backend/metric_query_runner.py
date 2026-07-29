"""Single-metric time-series query runner.

Returns a list of `(time_bucket, value)` points for one metric over a date
range, with a choice of aggregation. Modelled after the logs
`SparklineQueryRunner` shape but flattened — we don't yet need the full
`AnalyticsQueryRunner[LogsQueryResponse]` infrastructure since this product
isn't going through HogQL `DataNode` caching, schema-gen or the data-viz
pipeline yet.
"""

import re
import math
import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy
from products.metrics.backend.facade.enums import FilterOp, MetricType

AttributeScope = Literal["resource", "attribute", "auto"]

_ALLOWED_ATTRIBUTE_SCOPES: frozenset[str] = frozenset({"resource", "attribute", "auto"})

# Hard bound on bucketed rows per query; hitting it raises instead of
# silently truncating the tail of the time range (ORDER BY time ASC means
# the most recent buckets would be the ones dropped).
_ROW_LIMIT = 10000

# Widest queryable range. Counter/histogram queries scan raw samples within
# the range on the ClickHouse cluster shared with the live logs/traces
# products, so the span has to be bounded.
MAX_QUERY_SPAN = dt.timedelta(days=31)

# These run on the shared logs cluster; cap how much one query may read.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)

# The OTel service name is a first-class `metrics1` column (extracted at
# ingest from the `service.name` resource attribute); both spellings resolve
# to it so filters/group-bys match real ingested rows.
_SERVICE_NAME_KEYS: frozenset[str] = frozenset({"service_name", "service.name"})


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

    The empty-string fallback is documented behavior, not a bug: it means
    callers cannot meaningfully filter for "attribute equals empty string"
    in auto scope. Use an explicit scope for that edge case.

    ``service_name`` / ``service.name`` are special-cased to the first-class
    ``service_name`` column regardless of scope: ingestion extracts the
    service name out of the resource attributes into its own column, so a
    map lookup would match nothing on real rows.
    """
    if scope not in _ALLOWED_ATTRIBUTE_SCOPES:
        raise ValueError(f"Unknown attribute scope: {scope!r}")

    if name in _SERVICE_NAME_KEYS:
        return ast.Field(chain=["service_name"])

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


def _finite_or_none(value: float | None) -> float | None:
    """ClickHouse float aggregates can overflow to inf/-inf (or produce NaN);
    a non-finite value has no JSON representation and downstream renderers
    turn it into null anyway. Make the null explicit and deterministic here —
    consumers render it as a gap."""
    if value is None or not math.isfinite(value):
        return None
    return value


_ALLOWED_AGGREGATIONS: frozenset[str] = frozenset(
    {"sum", "avg", "count", "p95", "rate", "increase", "histogram_quantile"}
)

# Derived from the contract enum (whose values match what the ingest writes,
# rust/capture-logs `flatten_metric`) so the two can't silently diverge.
_ALLOWED_METRIC_TYPES: frozenset[str] = frozenset(t.value for t in MetricType)


def _histogram_quantile(quantile: float, bounds: list[float], counts: list[float]) -> float:
    """Prometheus-style quantile from explicit-bounds bucket counts.

    `counts` has one entry per bound plus an overflow bucket. Linear
    interpolation inside the bucket containing the rank; the overflow
    bucket clamps to the highest finite bound; the first bucket's lower
    edge is assumed 0 (negative-bound histograms get bounds[0]).
    """
    total = sum(counts)
    if total <= 0 or not bounds:
        return 0.0
    rank = quantile * total
    cumulative = 0.0
    for index, count in enumerate(counts):
        cumulative += count
        if cumulative >= rank:
            if index >= len(bounds):
                return bounds[-1]
            upper = bounds[index]
            lower = bounds[index - 1] if index > 0 else min(0.0, bounds[0])
            if count == 0:
                return upper
            return lower + (upper - lower) * (rank - (cumulative - count)) / count
    return bounds[-1]


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
    if filter.op in (FilterOp.REGEX, FilterOp.NOT_REGEX):
        # Pre-validate so a bad pattern is a 400, not a ClickHouse
        # CANNOT_COMPILE_REGEXP 500. Python `re` accepts a superset of RE2,
        # so this catches syntax errors without rejecting valid patterns.
        try:
            re.compile(filter.value)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression for filter {filter.key!r}: {exc}")
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
        quantile: float | None = None,
        metric_type: str | None = None,
    ) -> None:
        if aggregation not in _ALLOWED_AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation: {aggregation!r}")
        if metric_type is not None and metric_type not in _ALLOWED_METRIC_TYPES:
            raise ValueError(f"Unknown metric_type: {metric_type!r}")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if date_to - date_from > MAX_QUERY_SPAN:
            raise ValueError(f"date range too wide; the maximum span is {MAX_QUERY_SPAN.days} days")
        if interval is not None and interval not in {name for name, _, _ in _INTERVAL_LADDER}:
            raise ValueError(f"Unknown interval: {interval!r}")
        if interval is not None:
            step = next(step for name, step, _ in _INTERVAL_LADDER if name == interval)
            if (date_to - date_from) / step > _ROW_LIMIT:
                raise ValueError(
                    f"interval {interval!r} produces more than {_ROW_LIMIT} buckets over this range; "
                    "use a coarser interval or a narrower range"
                )
        if aggregation == "histogram_quantile":
            if quantile is None or not 0.0 < quantile < 1.0:
                raise ValueError("histogram_quantile requires a quantile in (0, 1)")

        self.team = team
        self.metric_name = metric_name
        self.aggregation = aggregation
        self.date_from = date_from
        self.date_to = date_to
        self.filters = tuple(filters)
        self.group_by = tuple(group_by)
        self.interval = interval or _pick_interval(date_from, date_to)
        self.quantile = quantile
        self.metric_type = metric_type

    def run(self) -> list[dict[str, Any]]:
        """Bucketed rows: `{"time", "value", "labels"}`. `labels` carries one
        entry per group_by key (always `{}` without group_by)."""
        if self.aggregation == "histogram_quantile":
            return self._run_histogram_quantile()
        if self.aggregation in ("rate", "increase"):
            query = self._build_counter_query()
        else:
            query = self._build_simple_query()

        response = execute_hogql_query(
            query_type="MetricQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )
        self._raise_on_truncation(response.results)

        group_count = len(self.group_by)
        rows: list[dict[str, Any]] = []
        for row in response.results:
            rows.append(
                {
                    "time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0],
                    "value": _finite_or_none(row[1 + group_count]),
                    "labels": {group.key: row[1 + index] for index, group in enumerate(self.group_by)},
                }
            )
        return rows

    def _run_histogram_quantile(self) -> list[dict[str, Any]]:
        """ClickHouse sums the per-le distributions (temporality-aware,
        per-series deltas like rate/increase); the quantile interpolation
        happens here in Python where it is exact and unit-testable."""
        assert self.quantile is not None
        query = self._build_histogram_query()
        response = execute_hogql_query(
            query_type="MetricQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=_QUERY_SETTINGS,
        )
        self._raise_on_truncation(response.results)

        group_count = len(self.group_by)
        distinct_bounds = {tuple(variant) for row in response.results for variant in row[2 + group_count] if variant}
        if len(distinct_bounds) > 1:
            raise ValueError(
                "histogram bounds differ across the selected series/time range; "
                "narrow the query with filters so all series share one bucket layout"
            )

        rows: list[dict[str, Any]] = []
        for row in response.results:
            bounds = list(row[1 + group_count])
            counts = list(row[3 + group_count])
            if sum(counts) <= 0:
                # No computable increase in this bucket (e.g. a cumulative
                # series' first sample has nothing to diff against). A gap is
                # honest; a fabricated quantile of 0 reads as "p95 is 0s".
                continue
            rows.append(
                {
                    "time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0],
                    "value": _finite_or_none(_histogram_quantile(self.quantile, bounds, counts)),
                    "labels": {group.key: row[1 + index] for index, group in enumerate(self.group_by)},
                }
            )
        return rows

    def _raise_on_truncation(self, results: list[Any]) -> None:
        """A full page means ClickHouse hit the row LIMIT and dropped the
        tail of the range (the most recent buckets) — fail loud rather than
        return data that silently ends early."""
        if len(results) >= _ROW_LIMIT:
            raise ValueError(
                "query produced too many (time bucket, group) rows; "
                "use a coarser interval, a narrower range, or a lower-cardinality group_by"
            )

    def _splice_group_columns(self, query: ast.SelectQuery) -> None:
        """Insert the group_by label columns between `time` and `value` —
        parse_select placeholders can't express a variable column count."""
        assert query.group_by is not None
        for index, group in enumerate(self.group_by):
            label_expr = ast.Call(name="toString", args=[attribute_field(group.key, scope=group.scope.value)])
            query.select.insert(1 + index, ast.Alias(alias=f"group_{index}", expr=label_expr))
            query.group_by.append(ast.Field(chain=[f"group_{index}"]))

    def _type_filter_expr(self) -> ast.Expr:
        """Constrains rows to one metric type. A name can exist as several
        types (a counter and a gauge); their series are distinct and must not
        blend into one aggregate. TRUE when no type was requested."""
        if self.metric_type is None:
            return ast.Constant(value=True)
        return parse_expr(
            "metric_type = {metric_type}", placeholders={"metric_type": ast.Constant(value=self.metric_type)}
        )

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
                  AND {type_filter}
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "aggregation": _aggregation_expr(self.aggregation),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": _filters_expr(self.filters),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
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
                        service_name AS service_name,
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
                            service_name,
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
                          AND {type_filter}
                    )
                )
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "divisor": ast.Constant(value=divisor),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": _filters_expr(self.filters),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query

    def _build_histogram_query(self) -> ast.SelectQuery:
        """Per-time-bucket summed bucket-count distributions for histogram
        rows, with the same per-series temporality/reset handling as
        rate/increase applied element-wise to the counts array."""
        query = parse_select(
            """
                SELECT
                    toStartOfInterval(sample_timestamp, {interval}) AS time,
                    any(histogram_bounds) AS bounds,
                    groupUniqArray(histogram_bounds) AS bounds_variants,
                    sumForEach(contribution_counts) AS counts
                FROM (
                    SELECT
                        timestamp AS sample_timestamp,
                        service_name AS service_name,
                        attributes AS attributes,
                        resource_attributes AS resource_attributes,
                        histogram_bounds AS histogram_bounds,
                        multiIf(
                            aggregation_temporality = 'delta', counts_f,
                            empty(prev_counts), arrayMap(x -> 0.0, counts_f),
                            length(prev_counts) != length(counts_f), counts_f,
                            arrayAll((c, p) -> c >= p, counts_f, prev_counts), arrayMap((c, p) -> c - p, counts_f, prev_counts),
                            counts_f
                        ) AS contribution_counts
                    FROM (
                        SELECT
                            timestamp,
                            service_name,
                            aggregation_temporality,
                            attributes,
                            resource_attributes,
                            histogram_bounds,
                            arrayMap(x -> toFloat(x), histogram_counts) AS counts_f,
                            lagInFrame(arrayMap(x -> toFloat(x), histogram_counts)) OVER (
                                PARTITION BY service_name, resource_fingerprint, toString(attributes)
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_counts
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND timestamp >= {date_from}
                          AND timestamp < {date_to}
                          AND notEmpty(histogram_counts)
                          AND {filters}
                          AND {type_filter}
                    )
                )
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": _filters_expr(self.filters),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query
