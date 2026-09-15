"""Run time-series queries for one metric.

Aggregate each physical series before combining series.
Metric points store a fingerprint. Series rows store label maps.
Filters use fingerprints, and group-by joins labels after reduction.
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

# Limit bucket rows. Raise an error instead of hiding recent buckets.
_ROW_LIMIT = 10000

# A series record updates every 30 minutes. The one-hour buffer allows late updates.
_SERIES_LAST_SEEN_BUFFER = dt.timedelta(hours=1)

# Limit the query range on the shared ClickHouse cluster.
# Counter and histogram queries read one bucket plus the predecessor lookback.
MAX_QUERY_SPAN = dt.timedelta(days=31)

# These queries use the shared logs cluster. Limit reads.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="throw",
)

# Ingestion extracts `service.name` to a column on both metrics tables.
# Map both spellings to that column for filters and group-bys.
_SERVICE_NAME_KEYS: frozenset[str] = frozenset({"service_name", "service.name"})


def attribute_field(name: str, *, scope: AttributeScope = "auto") -> ast.Expr:
    """Return a HogQL AST expression for a metric attribute.

    Labels are in `metric_series`. `scope` selects a resource, attribute, or
    resource-first map. Use an explicit scope to match empty strings.
    Service name always uses the extracted `service_name` column.
    """
    if scope not in _ALLOWED_ATTRIBUTE_SCOPES:
        raise ValueError(f"Unknown attribute scope: {scope!r}")

    if name in _SERVICE_NAME_KEYS:
        return ast.Field(chain=["service_name"])

    name_constant = ast.Constant(value=name)

    # Use `arrayElement`. Subscript syntax is invalid on physical Map columns.
    # It is ClickHouse's Map accessor and returns an empty string for missing keys.
    if scope == "resource":
        return parse_expr("arrayElement(resource_attributes, {name})", placeholders={"name": name_constant})
    if scope == "attribute":
        return parse_expr("arrayElement(attributes, {name})", placeholders={"name": name_constant})
    return parse_expr(
        "if(arrayElement(resource_attributes, {name}) != '', arrayElement(resource_attributes, {name}), arrayElement(attributes, {name}))",
        placeholders={"name": name_constant},
    )


def _series_key_expr() -> ast.Expr:
    """Return the key for one physical series.

    Ingestion includes name, type, service, and labels. It excludes
    `$originalTimestamp`.
    """
    return ast.Field(chain=["series_fingerprint"])


def _aggregation_expr(name: str, value: ast.Expr) -> ast.Expr:
    """Return a HogQL AST for cross-series aggregation.

    The inner query returns one value per series. This prevents scrape rate
    from changing the result. `count` therefore counts series.
    """
    if name == "sum":
        return ast.Call(name="sum", args=[value])
    if name == "avg":
        return ast.Call(name="avg", args=[value])
    if name == "count":
        return ast.Call(name="count", args=[])
    if name == "min":
        return ast.Call(name="min", args=[value])
    if name == "max":
        return ast.Call(name="max", args=[value])
    if name == "p95":
        return ast.Call(name="quantile", params=[ast.Constant(value=0.95)], args=[value])
    raise ValueError(f"Unsupported aggregation: {name!r}")


def _finite_or_none(value: float | None) -> float | None:
    """Return null for non-finite values so clients render a gap."""
    if value is None or not math.isfinite(value):
        return None
    return value


_ALLOWED_AGGREGATIONS: frozenset[str] = frozenset(
    {"sum", "avg", "count", "min", "max", "p95", "rate", "increase", "histogram_quantile"}
)

# Derive this from the contract enum to match ingestion values.
_ALLOWED_METRIC_TYPES: frozenset[str] = frozenset(t.value for t in MetricType)


def _histogram_quantile(quantile: float, bounds: list[float], counts: list[float]) -> float:
    """Calculate a Prometheus-style quantile from bounded bucket counts.

    Interpolate in the selected bucket. Clamp overflow to the highest bound.
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


# Target about 60 chart buckets.
_TARGET_BUCKET_COUNT = 60

# List intervals from finest to coarsest.
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
    """Floor a timestamp to the ClickHouse bucket grid.

    Use the project timezone to keep the first bucket complete. Do not use
    `interval_specs.align`, which uses different week and sub-hour rules.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.UTC)
    local = timestamp.astimezone(tzinfo)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval == "week":
        # ClickHouse week intervals start on Monday. `toStartOfWeek` defaults to Sunday.
        return (midnight - dt.timedelta(days=midnight.weekday())).astimezone(dt.UTC)
    if interval == "day":
        return midnight.astimezone(dt.UTC)
    # Use elapsed time from local midnight. This keeps DST boundaries aligned.
    step = _interval_step(interval)
    return midnight.astimezone(dt.UTC) + (local.astimezone(dt.UTC) - midnight.astimezone(dt.UTC)) // step * step


# Use Prometheus's default lookback. It supports scrapes slower than a bucket.
# A five-minute lookback reads the same hourly granules as a shorter one.
_MIN_COUNTER_LOOKBACK = dt.timedelta(minutes=5)


def counter_lookback(interval: str) -> dt.timedelta:
    """Return the counter and histogram predecessor lookback.

    The first in-range sample needs its prior sample. Queries remove pre-range
    rows before returning results. Diagnostics uses the same lookback.
    """
    return max(_interval_step(interval), _MIN_COUNTER_LOOKBACK)


def _filter_condition(filter: MetricFilter) -> ast.Expr:
    """Return one label predicate as a HogQL boolean expression.

    Negative matchers include missing map keys, as in Prometheus.
    """
    field = attribute_field(filter.key, scope=filter.scope.value)
    if filter.op in (FilterOp.REGEX, FilterOp.NOT_REGEX):
        # Return 400 for invalid patterns. Python accepts all valid RE2 syntax.
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


def time_range_expr(date_from: dt.datetime, date_to: dt.datetime) -> ast.Expr:
    """Limit a `metrics` read to `[date_from, date_to)`.

    Timestamp gives the exact range. UTC `time_bucket` lets ClickHouse skip
    granules.
    """
    return parse_expr(
        """
            timestamp >= {date_from}
            AND timestamp < {date_to}
            AND time_bucket >= {bucket_from}
            AND time_bucket <= {bucket_to}
        """,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "bucket_from": ast.Constant(value=_utc_hour(date_from)),
            "bucket_to": ast.Constant(value=_utc_hour(date_to)),
        },
    )


def _utc_hour(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC).replace(minute=0, second=0, microsecond=0)


def type_filter_expr(metric_type: str | None) -> ast.Expr:
    """Limit rows to one metric type.

    The same name can have distinct counter and gauge series. Return true when
    no type was requested.
    """
    if metric_type is None:
        return ast.Constant(value=True)
    return parse_expr("metric_type = {metric_type}", placeholders={"metric_type": ast.Constant(value=metric_type)})


def _active_since_expr(date_from: dt.datetime | None) -> ast.Expr:
    """Bound a `metric_series` read to series that could have later samples.

    Keep a one-hour buffer for delayed series updates. `metric_series2` indexes
    `last_seen`, so the bound skips old parts.

    TRUE when `date_from` is None, for callers (the bucket decomposition) that
    want every series regardless of when it was last seen.
    """
    if date_from is None:
        return ast.Constant(value=True)
    return parse_expr(
        "last_seen >= {date_from}",
        placeholders={"date_from": ast.Constant(value=date_from - _SERIES_LAST_SEEN_BUFFER)},
    )


def series_scope_expr(
    metric_name: str, filters: Sequence[MetricFilter], date_from: dt.datetime | None = None
) -> ast.Expr:
    """Limit `metrics` rows to series that match label filters.

    Labels are in `metric_series`, so filters select matching fingerprints.
    Without filters, points with missing series rows still count.
    """
    if not filters:
        return ast.Constant(value=True)
    return parse_expr(
        """
            series_fingerprint IN (
                SELECT series_fingerprint
                FROM posthog.metric_series
                WHERE metric_name = {metric_name}
                  AND {active_since}
                  AND {filters}
            )
        """,
        placeholders={
            "metric_name": ast.Constant(value=metric_name),
            "active_since": _active_since_expr(date_from),
            "filters": filters_expr(filters),
        },
    )


def series_labels_query(metric_name: str, date_from: dt.datetime | None = None) -> ast.SelectQuery:
    """Return full label maps for each metric series.

    Group rows to avoid duplicate joins. `date_from` limits active series.
    Without it, return every series for bucket decomposition.
    """
    query = parse_select(
        """
            SELECT
                series_fingerprint,
                any(service_name) AS service_name,
                any(attributes) AS attributes,
                any(resource_attributes) AS resource_attributes
            FROM posthog.metric_series
            WHERE metric_name = {metric_name}
              AND {active_since}
            GROUP BY series_fingerprint
        """,
        placeholders={"metric_name": ast.Constant(value=metric_name), "active_since": _active_since_expr(date_from)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def series_group_labels_query(
    metric_name: str, group_by: Sequence[MetricGroupBy], date_from: dt.datetime | None = None
) -> ast.SelectQuery:
    """Return group-by labels for each series as `group_0`, `group_1`, and so on.

    Read only the group labels to avoid joining full maps. `any()` is safe
    because labels are constant within a series.
    """
    query = parse_select(
        """
            SELECT series_fingerprint
            FROM posthog.metric_series
            WHERE metric_name = {metric_name}
              AND {active_since}
            GROUP BY series_fingerprint
        """,
        placeholders={"metric_name": ast.Constant(value=metric_name), "active_since": _active_since_expr(date_from)},
    )
    assert isinstance(query, ast.SelectQuery)
    for index, group in enumerate(group_by):
        label = ast.Call(name="toString", args=[attribute_field(group.key, scope=group.scope.value)])
        query.select.append(ast.Alias(alias=f"group_{index}", expr=ast.Call(name="any", args=[label])))
    return query


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
        # Start at the bucket boundary so the first bucket is complete.
        self.date_from = _align_to_interval(date_from, self.interval, tzinfo=team.timezone_info)
        self.date_to = date_to
        self.filters = tuple(filters)
        self.group_by = tuple(group_by)
        self.quantile = quantile
        self.metric_type = metric_type

    def run(self) -> list[dict[str, Any]]:
        """Return bucketed rows with time, value, and group labels."""
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
        """Calculate quantiles from the distributions that ClickHouse sums."""
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
                # The bucket has no computable increase. Return a gap, not zero.
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
        """Raise an error when the row limit drops recent buckets."""
        if len(results) >= _ROW_LIMIT:
            raise ValueError(
                "query produced too many (time bucket, group) rows; "
                "use a coarser interval, a narrower range, or a lower-cardinality group_by"
            )

    def _splice_group_columns(self, query: ast.SelectQuery) -> None:
        """Add group labels between `time` and `value`.

        Join series labels by fingerprint only when the query groups results.
        Missing series rows use empty labels.
        """
        if not self.group_by:
            return
        assert query.group_by is not None
        assert query.select_from is not None and query.select_from.alias == "s"
        query.select_from.next_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=series_group_labels_query(self.metric_name, self.group_by, self.date_from),
            alias="ser",
            constraint=ast.JoinConstraint(
                expr=parse_expr("s.series_fingerprint = ser.series_fingerprint"), constraint_type="ON"
            ),
        )
        # The joined query resolves labels as `group_i`.
        # The outer query reads `ser.group_i`, not label maps.
        for index in range(len(self.group_by)):
            alias = f"group_{index}"
            query.select.insert(1 + index, ast.Alias(alias=alias, expr=ast.Field(chain=["ser", alias])))
            query.group_by.append(ast.Field(chain=[alias]))

    def _type_filter_expr(self) -> ast.Expr:
        return type_filter_expr(self.metric_type)

    def _series_scope_expr(self) -> ast.Expr:
        return series_scope_expr(self.metric_name, self.filters, self.date_from)

    def _build_simple_query(self) -> ast.SelectQuery:
        """Build sum, average, count, and p95 queries.

        Reduce each series to its last value per bucket before aggregation.
        Group-by joins labels by fingerprint after reduction.
        """
        # `metrics` is registered only in the `posthog.` HogQL namespace.
        query = parse_select(
            """
                SELECT
                    time AS time,
                    {aggregation} AS value
                FROM (
                    SELECT
                        toStartOfInterval(timestamp, {interval}) AS time,
                        series_fingerprint AS series_fingerprint,
                        argMax(value, timestamp) AS series_value
                    FROM posthog.metrics
                    WHERE metric_name = {metric_name}
                      AND {time_range}
                      AND {series_scope}
                      AND {type_filter}
                    GROUP BY time, {series_key}
                ) AS s
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "aggregation": _aggregation_expr(self.aggregation, ast.Field(chain=["series_value"])),
                "metric_name": ast.Constant(value=self.metric_name),
                "time_range": time_range_expr(self.date_from, self.date_to),
                "series_scope": self._series_scope_expr(),
                "series_key": _series_key_expr(),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query

    def _build_counter_query(self) -> ast.SelectQuery:
        """Build rate and increase queries from per-series deltas.

        Cumulative metrics diff each sample and handle resets. Delta metrics
        use sample values. Missing predecessors produce gaps. The lookback
        provides a predecessor before the requested range.
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
                        series_fingerprint AS series_fingerprint,
                        multiIf(
                            aggregation_temporality = 'delta', value,
                            isNull(prev_value), NULL,
                            value >= assumeNotNull(prev_value), value - assumeNotNull(prev_value),
                            value
                        ) AS contribution
                    FROM (
                        SELECT
                            timestamp,
                            series_fingerprint,
                            value,
                            aggregation_temporality,
                            lagInFrame(toNullable(value)) OVER (
                                PARTITION BY {series_key}
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_value
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND {scan_range}
                          AND {series_scope}
                          AND {type_filter}
                    )
                ) AS s
                WHERE sample_timestamp >= {date_from}
                GROUP BY time
                HAVING isNotNull(value)
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "divisor": ast.Constant(value=divisor),
                "series_key": _series_key_expr(),
                "metric_name": ast.Constant(value=self.metric_name),
                "scan_range": time_range_expr(self.date_from - counter_lookback(self.interval), self.date_to),
                "date_from": ast.Constant(value=self.date_from),
                "series_scope": self._series_scope_expr(),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query

    def _build_histogram_query(self) -> ast.SelectQuery:
        """Build histogram distributions with rate and increase semantics."""
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
                        series_fingerprint AS series_fingerprint,
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
                            series_fingerprint,
                            aggregation_temporality,
                            histogram_bounds,
                            arrayMap(x -> toFloat(x), histogram_counts) AS counts_f,
                            lagInFrame(arrayMap(x -> toFloat(x), histogram_counts)) OVER (
                                PARTITION BY {series_key}
                                ORDER BY timestamp ASC
                                ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING
                            ) AS prev_counts
                        FROM posthog.metrics
                        WHERE metric_name = {metric_name}
                          AND {scan_range}
                          AND notEmpty(histogram_counts)
                          AND {series_scope}
                          AND {type_filter}
                    )
                ) AS s
                WHERE sample_timestamp >= {date_from}
                GROUP BY time
                ORDER BY time ASC
                LIMIT {row_limit}
            """,
            placeholders={
                "interval": _interval_expr(self.interval),
                "series_key": _series_key_expr(),
                "metric_name": ast.Constant(value=self.metric_name),
                "scan_range": time_range_expr(self.date_from - counter_lookback(self.interval), self.date_to),
                "date_from": ast.Constant(value=self.date_from),
                "series_scope": self._series_scope_expr(),
                "type_filter": self._type_filter_expr(),
                "row_limit": ast.Constant(value=_ROW_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        self._splice_group_columns(query)
        return query
