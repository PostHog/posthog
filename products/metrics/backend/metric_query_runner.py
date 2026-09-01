"""Single-metric time-series query runner.

Returns a list of `(time_bucket, value)` points for one metric over a date
range, with a choice of aggregation. Modelled after the logs
`SparklineQueryRunner` shape but flattened — we don't yet need the full
`AnalyticsQueryRunner[LogsQueryResponse]` infrastructure since this product
isn't going through HogQL `DataNode` caching, schema-gen or the data-viz
pipeline yet.

Every aggregation resolves per physical series (`_series_key_exprs`) before
combining across series: instant aggregations reduce each series to its last
sample in the bucket, counter functions diff within a series. Aggregating raw
samples instead would weight a series by how often it was scraped.
"""

import re
import math
import datetime as dt
from collections.abc import Sequence
from typing import Any, Literal
from zoneinfo import ZoneInfo

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
# products, so the span has to be bounded. The bound stays on the requested
# range: `date_from` snaps back to its bucket boundary and the counter and
# histogram scans reach a further `counter_lookback(interval)` for a
# predecessor sample, so the scan exceeds the request by under one interval
# step plus the lookback (up to two weeks of extra daily partitions at the
# `week` interval, a single one on the common sub-day charts).
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

# Synthetic per-data-point attribute ingest stamps on a point whose timestamp it
# had to override. Never part of a series' identity — see `_series_key_exprs`.
_ORIGINAL_TIMESTAMP_KEY = "$originalTimestamp"


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


def _series_key_exprs() -> list[ast.Expr]:
    """Identifies the physical series a row belongs to.

    Every aggregation resolves per series before combining across series, so
    all three query builders share this definition rather than restating it.

    `metric_type` belongs to the identity, not just to filtering: one name can
    be ingested as both a counter and a gauge, and `metric_type` is optional on
    the query, so an unconstrained query sees both sets of rows at once.

    `$originalTimestamp` is dropped back out of `attributes`. Ingest adds it to
    the map for a point whose timestamp is more than a day off, carrying a
    per-sample value, and deliberately fingerprints the series before adding it
    (`compute_series_fingerprint` in `rust/capture-logs/src/metric_record.rs`).
    Keeping it would shatter a skewed exporter's series into one series per
    sample, which is the exact weighting these keys exist to prevent.

    `resource_attributes` appears here rather than its `resource_fingerprint`
    digest so that the key stays exact — a hash collision would merge two
    targets into one series.

    These are grouping and partitioning keys only; a query that also needs the
    attributes themselves reads them off `posthog.metrics` in the same scope,
    because a column aliased `attributes` in a scope that already resolves the
    `attributes` map collides with it.
    """
    return [
        ast.Field(chain=["service_name"]),
        ast.Field(chain=["resource_attributes"]),
        parse_expr(
            "mapFilter((k, v) -> k != {synthetic}, attributes)",
            placeholders={"synthetic": ast.Constant(value=_ORIGINAL_TIMESTAMP_KEY)},
        ),
        ast.Field(chain=["metric_type"]),
    ]


def _aggregation_expr(name: str, value: ast.Expr) -> ast.Expr:
    """Build the HogQL AST for the cross-series aggregations.

    `value` is the per-series value the inner query produced, never the raw
    `value` column: aggregating raw rows counts each series once per sample, so
    the result scales with the scrape rate. `count` takes no argument for the
    same reason — one inner row per series means it counts series.

    Kept as AST nodes (rather than string interpolation) so the
    `hogql-no-fstring` semgrep rule doesn't have to special-case this
    runner — the function name and percentile literal travel as a
    typed expression, not as substituted text.
    """
    if name == "sum":
        return ast.Call(name="sum", args=[value])
    if name == "avg":
        return ast.Call(name="avg", args=[value])
    if name == "count":
        return ast.Call(name="count", args=[])
    if name == "p95":
        return ast.Call(name="quantile", params=[ast.Constant(value=0.95)], args=[value])
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


def _interval_step(name: str) -> dt.timedelta:
    for entry_name, step, _ in _INTERVAL_LADDER:
        if entry_name == name:
            return step
    raise ValueError(f"Unknown interval: {name!r}")


def _align_to_interval(timestamp: dt.datetime, interval: str, *, tzinfo: ZoneInfo) -> dt.datetime:
    """Floor `timestamp` onto the bucket grid `toStartOfInterval` uses.

    The bucket labels come from `toStartOfInterval(sample_timestamp)`, so a
    `date_from` inside a bucket would make that first bucket partial: labelled
    as the whole interval but covering only the slice after `date_from`. Every
    query scans and clips from this floor instead, so the first bucket holds
    its full interval. Relative ranges like "-1h" resolve to now-minus-offset
    with second precision, which makes the unaligned case the normal one.

    The grid lives in `tzinfo`, the project's timezone, not in UTC. HogQL
    rewrites a `DateTime` column read into `toTimeZone(<column>, <project
    timezone>)` (`PropertySwapper.visit_field`), so `toStartOfInterval` sees a
    local-time value and counts every step from local midnight. Flooring in UTC
    instead lands on the same instant for the sub-hour steps, but drifts for
    `hour_6`, `day` and `week`, and for `hour` in a zone whose offset is not a
    whole number of hours (Asia/Kolkata is +05:30, so its hour boundaries sit
    at :30 past each UTC hour).

    Not `posthog.interval_specs.align`: that grid honors the team's
    `week_start_day` and lacks the sub-hour steps, where `toStartOfInterval`
    always counts weeks from Monday — the two would disagree exactly where
    agreement with the SQL is the point.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.UTC)
    local = timestamp.astimezone(tzinfo)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "week":
        # ClickHouse's week interval starts on Monday, unlike its own
        # `toStartOfWeek`, which defaults to Sunday.
        return (midnight - dt.timedelta(days=midnight.weekday())).astimezone(dt.UTC)
    if interval == "day":
        return midnight.astimezone(dt.UTC)
    # ClickHouse counts elapsed seconds from the midnight instant, so this adds
    # a real duration rather than doing wall-clock arithmetic. A day shortened
    # or lengthened by a DST transition then keeps both grids on the same
    # boundaries.
    step = _interval_step(interval)
    return midnight.astimezone(dt.UTC) + (local.astimezone(dt.UTC) - midnight.astimezone(dt.UTC)) // step * step


# Prometheus's default lookback delta. One interval step on its own is not
# enough when the scrape interval is coarser than the bucket — a 60s scrape on
# a `second` or `minute` chart — and `metrics1` is partitioned by day with
# `timestamp` last in the sort key, so reaching back five minutes inside a day
# reads the same partitions as reaching back one.
_MIN_COUNTER_LOOKBACK = dt.timedelta(minutes=5)


def counter_lookback(interval: str) -> dt.timedelta:
    """How far before `date_from` the counter and histogram scans reach.

    Those aggregations diff each sample against the one before it, so the last
    sample *outside* the requested range is an input to the first bucket inside
    it. Without it the first bucket diffs against nothing and is dropped as
    uncomputable. The pre-range rows are cut again before bucketing, so the
    returned grid is exactly the requested range.

    `diagnostics.decompose_bucket` reads its raw samples over the same window
    through this helper: a shorter reach there would find a different
    predecessor and report a disagreement the chart does not have.
    """
    return max(_interval_step(interval), _MIN_COUNTER_LOOKBACK)


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


def filters_expr(filters: Sequence[MetricFilter]) -> ast.Expr:
    """AND of all filter conditions; TRUE when there are none."""
    if not filters:
        return ast.Constant(value=True)
    conditions = [_filter_condition(f) for f in filters]
    if len(conditions) == 1:
        return conditions[0]
    return ast.And(exprs=conditions)


def type_filter_expr(metric_type: str | None) -> ast.Expr:
    """Constrains rows to one metric type. A name can exist as several
    types (a counter and a gauge); their series are distinct and must not
    blend into one aggregate. TRUE when no type was requested.

    Both `metrics` and `metric_series` name the column `metric_type`, so the
    same expression works against either table."""
    if metric_type is None:
        return ast.Constant(value=True)
    return parse_expr("metric_type = {metric_type}", placeholders={"metric_type": ast.Constant(value=metric_type)})


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
            step = _interval_step(interval)
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
        self.interval = interval or _pick_interval(date_from, date_to)
        # Validation above bounds the requested range; the scan then starts at
        # the bucket boundary so the first bucket covers its whole interval.
        self.date_from = _align_to_interval(date_from, self.interval, tzinfo=team.timezone_info)
        self.date_to = date_to
        self.filters = tuple(filters)
        self.group_by = tuple(group_by)
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

    def _splice_group_columns(self, query: ast.SelectQuery, *, resolve_in: ast.SelectQuery | None = None) -> None:
        """Insert the group_by label columns between `time` and `value` —
        parse_select placeholders can't express a variable column count.

        `attribute_field` resolves against the scope of the query it lands in,
        so that query must expose `service_name`, `attributes` and
        `resource_attributes` under those names — read straight off
        `posthog.metrics`, or re-exported from a subquery. Pass `resolve_in`
        when the labels have to be built a level down instead; `query` then
        only forwards them up by name.
        """
        assert query.group_by is not None
        for index, group in enumerate(self.group_by):
            alias = f"group_{index}"
            label_expr: ast.Expr = ast.Call(name="toString", args=[attribute_field(group.key, scope=group.scope.value)])
            if resolve_in is not None:
                assert resolve_in.group_by is not None
                resolve_in.select.append(ast.Alias(alias=alias, expr=label_expr))
                resolve_in.group_by.append(ast.Field(chain=[alias]))
                label_expr = ast.Field(chain=[alias])
            query.select.insert(1 + index, ast.Alias(alias=alias, expr=label_expr))
            query.group_by.append(ast.Field(chain=[alias]))

    def _type_filter_expr(self) -> ast.Expr:
        return type_filter_expr(self.metric_type)

    def _build_simple_query(self) -> ast.SelectQuery:
        """sum/avg/count/p95: collapse each series to one value per bucket,
        then aggregate across series — PromQL instant-vector semantics.

        The inner query takes each series' last sample in the bucket, so a
        metric scraped ten times contributes once rather than ten times.
        Aggregating raw rows instead multiplied the cross-series total by the
        scrape count, and the multiplier moved with partial buckets and
        dropped scrapes.

        Two samples of one series sharing a timestamp (a duplicate scrape)
        make `argMax` pick between them arbitrarily; they are the same
        reading, so either answer is right.

        Group-by labels are built in the inner query, where the attribute maps
        are still in scope. A label is constant within a series, so the outer
        query just carries it up.
        """
        # `metrics` is only registered under the `posthog.` HogQL namespace
        # (see posthog/hogql/database/database.py).
        query = parse_select(
            """
                SELECT
                    time AS time,
                    {aggregation} AS value
                FROM (
                    SELECT
                        toStartOfInterval(timestamp, {interval}) AS time,
                        argMax(value, timestamp) AS series_value
                    FROM posthog.metrics
                    WHERE metric_name = {metric_name}
                      AND timestamp >= {date_from}
                      AND timestamp < {date_to}
                      AND {filters}
                      AND {type_filter}
                    GROUP BY time
                )
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "aggregation": _aggregation_expr(self.aggregation, ast.Field(chain=["series_value"])),
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": filters_expr(self.filters),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        # Appended rather than written into the template so the key stays
        # defined in exactly one place; a placeholder can only carry one
        # expression.
        inner = query.select_from.table if query.select_from else None
        assert isinstance(inner, ast.SelectQuery) and inner.group_by is not None
        inner.group_by.extend(_series_key_exprs())
        self._splice_group_columns(query, resolve_in=inner)
        return query

    def _build_counter_query(self) -> ast.SelectQuery:
        """rate/increase: per-underlying-series deltas, then aggregate.

        Each physical series (service_name, resource_fingerprint, datapoint
        attributes) gets its samples diffed in timestamp order via a window
        function, Prometheus-style:

        - cumulative temporality: contribution = value - prev, clamped for
          counter resets (value < prev means the counter restarted, so the
          post-reset absolute value IS the increase); a sample with no
          predecessor within `counter_lookback` has an unknowable increase, so
          it contributes NULL, and a bucket where nothing was computable is
          dropped rather than plotted as 0 (the histogram path drops such
          buckets too).
        - delta temporality: each sample already is the increase, so it
          contributes its own value.

        `increase` sums contributions per bucket; `rate` divides by the
        bucket length in seconds.

        The scan starts a lookback before `date_from` so the first sample in
        the range has a predecessor to diff against; the outer `WHERE` drops
        those pre-range rows again, leaving the requested bucket grid.
        """
        step_seconds = _interval_step(self.interval).total_seconds()
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
                            isNull(prev_value), NULL,
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
                                PARTITION BY {series_key}
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_value
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND timestamp >= {scan_from}
                          AND timestamp < {date_to}
                          AND {filters}
                          AND {type_filter}
                    )
                )
                WHERE sample_timestamp >= {date_from}
                GROUP BY time
                HAVING isNotNull(value)
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "divisor": ast.Constant(value=divisor),
                "series_key": ast.Tuple(exprs=_series_key_exprs()),
                "metric_name": ast.Constant(value=self.metric_name),
                "scan_from": ast.Constant(value=self.date_from - counter_lookback(self.interval)),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": filters_expr(self.filters),
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
        rate/increase applied element-wise to the counts array — including the
        lookback that gives the first in-range sample a predecessor."""
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
                                PARTITION BY {series_key}
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_counts
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND timestamp >= {scan_from}
                          AND timestamp < {date_to}
                          AND notEmpty(histogram_counts)
                          AND {filters}
                          AND {type_filter}
                    )
                )
                WHERE sample_timestamp >= {date_from}
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "series_key": ast.Tuple(exprs=_series_key_exprs()),
                "metric_name": ast.Constant(value=self.metric_name),
                "scan_from": ast.Constant(value=self.date_from - counter_lookback(self.interval)),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "filters": filters_expr(self.filters),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query
