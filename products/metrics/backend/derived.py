"""Derived metrics: series that a query computes from spans and logs.

A derived metric reads the existing `trace_spans` and `logs` rows and writes nothing,
so it adds no storage and no metrics ingestion. Saved insights keep the metric name,
so a later ingestion-time rollup can serve the same names without changes for users.
"""

import datetime as dt
from enum import StrEnum

from django.core.cache import cache
from django.utils import timezone

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.permissions import posthog_feature_flag_enabled

from products.metrics.backend.facade.contracts import (
    DERIVED_METRIC_PREFIX,
    METRICS_DERIVED_SERIES_FEATURE_FLAG,
    MetricQueryClause,
    MetricQueryTooManyRowsError,
)
from products.metrics.backend.facade.enums import MetricAggregation, MetricRangeFunction, MetricType
from products.metrics.backend.metric_query_runner import (
    AttributeScope,
    _align_to_interval,
    _finite_or_none,
    _interval_expr,
    _interval_step,
    _resolve_interval,
    attribute_field,
    filters_expr,
)

logger = structlog.get_logger(__name__)

# Spans and logs are raw rows, not pre-aggregated samples, so a derived query reads more
# than a metric query over the same range. These caps keep its cost close to a logs query.
MAX_DERIVED_QUERY_SPAN = dt.timedelta(days=7)
MAX_DERIVED_GROUP_BY_KEYS = 2
_ROW_LIMIT = 10000
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_execution_time=30,
    max_bytes_to_read=10_000_000_000,
    read_overflow_mode="throw",
)

_DATA_PRESENCE_WINDOW = dt.timedelta(hours=24)
_DATA_PRESENCE_CACHE_TTL_SECONDS = 300


class DerivedSource(StrEnum):
    SPANS = "spans"
    LOGS = "logs"


class DerivedValue(StrEnum):
    COUNT = "count"
    ERROR_COUNT = "error_count"
    DURATION_MS = "duration_ms"


@frozen
class DerivedMetric:
    name: str
    source: DerivedSource
    value: DerivedValue
    metric_type: MetricType
    unit: str
    description: str


DERIVED_METRICS: tuple[DerivedMetric, ...] = (
    DerivedMetric(
        name=f"{DERIVED_METRIC_PREFIX}spans.requests",
        source=DerivedSource.SPANS,
        value=DerivedValue.COUNT,
        metric_type=MetricType.SUM,
        unit="{request}",
        description="Requests per service: server spans, or root spans for a service without server spans.",
    ),
    DerivedMetric(
        name=f"{DERIVED_METRIC_PREFIX}spans.errors",
        source=DerivedSource.SPANS,
        value=DerivedValue.ERROR_COUNT,
        metric_type=MetricType.SUM,
        unit="{request}",
        description="Requests with an error status.",
    ),
    DerivedMetric(
        name=f"{DERIVED_METRIC_PREFIX}spans.duration",
        source=DerivedSource.SPANS,
        value=DerivedValue.DURATION_MS,
        metric_type=MetricType.HISTOGRAM,
        unit="ms",
        description="Request duration in milliseconds.",
    ),
    DerivedMetric(
        name=f"{DERIVED_METRIC_PREFIX}logs.records",
        source=DerivedSource.LOGS,
        value=DerivedValue.COUNT,
        metric_type=MetricType.SUM,
        unit="{record}",
        description="Log records per service and severity.",
    ),
)

_DERIVED_METRICS_BY_NAME: dict[str, DerivedMetric] = {metric.name: metric for metric in DERIVED_METRICS}

_TABLES: dict[DerivedSource, list[str | int]] = {
    DerivedSource.SPANS: ["posthog", "trace_spans"],
    DerivedSource.LOGS: ["logs"],
}

# Keys that map to a column. Other keys read the attribute maps, as for ingested metrics.
_COLUMN_KEYS: dict[DerivedSource, dict[str, str]] = {
    DerivedSource.SPANS: {"span.name": "name"},
    DerivedSource.LOGS: {"severity_text": "severity_text"},
}

_COUNTER_AGGREGATIONS = frozenset({MetricAggregation.SUM, MetricAggregation.INCREASE, MetricAggregation.RATE})
_HISTOGRAM_AGGREGATIONS = frozenset(
    {
        MetricAggregation.QUANTILE,
        MetricAggregation.HISTOGRAM_QUANTILE,
        MetricAggregation.AVG,
        MetricAggregation.MIN,
        MetricAggregation.MAX,
    }
)

# A request is a server span. A service that has no server spans in the window counts its root
# spans, so a consumer's client spans count once each. This matches the APM service health.
_REQUEST_PREDICATE = """
    (kind = 2 OR (is_root_span AND service_name NOT IN (
        SELECT service_name FROM posthog.trace_spans WHERE {window} AND kind = 2
    )))
"""


def is_derived_metric_name(name: str) -> bool:
    return name.startswith(DERIVED_METRIC_PREFIX)


def get_derived_metric(name: str) -> DerivedMetric:
    metric = _DERIVED_METRICS_BY_NAME.get(name)
    if metric is None:
        known = ", ".join(sorted(_DERIVED_METRICS_BY_NAME))
        raise ValueError(f"Unknown derived metric {name!r}. Derived metrics: {known}")
    return metric


def derived_metrics_enabled(team: Team) -> bool:
    try:
        return posthog_feature_flag_enabled(
            METRICS_DERIVED_SERIES_FEATURE_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    except Exception:
        logger.warning("metrics_derived_series_flag_check_failed", team_id=team.id)
        return False


def _window_expr(date_from: dt.datetime, date_to: dt.datetime) -> ast.Expr:
    # `time_bucket` is a sub-day floor of `timestamp`, so the UTC day of `date_from` bounds it.
    day_from = date_from.astimezone(dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return parse_expr(
        "timestamp >= {date_from} AND timestamp < {date_to} AND time_bucket >= {day_from} AND time_bucket <= {date_to}",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "day_from": ast.Constant(value=day_from),
        },
    )


def _sources_with_data(team: Team) -> set[DerivedSource]:
    cache_key = f"metrics:{team.id}:derived_sources:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return {DerivedSource(source) for source in cached}

    now = timezone.now()
    window = _window_expr(now - _DATA_PRESENCE_WINDOW, now)
    sources: set[DerivedSource] = set()
    for source, table in _TABLES.items():
        query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(table=ast.Field(chain=table)),
            where=window,
            limit=ast.Constant(value=1),
        )
        response = execute_hogql_query(
            query_type="DerivedMetricsPresenceQuery",
            query=query,
            team=team,
            workload=Workload.LOGS,
            settings=_QUERY_SETTINGS,
        )
        if response.results:
            sources.add(source)
    cache.set(cache_key, sorted(sources), _DATA_PRESENCE_CACHE_TTL_SECONDS)
    return sources


def list_derived_metric_names(team: Team, *, search: str = "") -> list[DerivedMetric]:
    """The derived metrics a team can query: those whose source has data in the last day."""
    sources = _sources_with_data(team)
    needle = search.strip().lower()
    return [
        metric
        for metric in DERIVED_METRICS
        if metric.source in sources and (not needle or needle in metric.name.lower())
    ]


class DerivedMetricQueryRunner:
    """Bucketed rows for one derived-metric clause, in the row shape of `MetricQueryRunner.run`."""

    def __init__(
        self,
        *,
        team: Team,
        clause: MetricQueryClause,
        date_from: dt.datetime,
        date_to: dt.datetime,
        interval: str | None,
    ) -> None:
        metric = get_derived_metric(clause.metric_name)
        if metric.metric_type is MetricType.HISTOGRAM:
            if clause.aggregation not in _HISTOGRAM_AGGREGATIONS:
                raise ValueError(
                    f"{metric.name} supports the quantile, histogram_quantile, avg, min and max aggregations"
                )
            if clause.range_function is not None:
                raise ValueError(f"{metric.name} does not support a range function")
        elif clause.aggregation not in _COUNTER_AGGREGATIONS:
            raise ValueError(f"{metric.name} supports the sum, increase and rate aggregations")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if date_to - date_from > MAX_DERIVED_QUERY_SPAN:
            raise ValueError(
                f"date range too wide for a derived metric; the maximum span is {MAX_DERIVED_QUERY_SPAN.days} days"
            )
        if len(clause.group_by) > MAX_DERIVED_GROUP_BY_KEYS:
            raise ValueError(f"a derived metric can group by at most {MAX_DERIVED_GROUP_BY_KEYS} keys")

        self.team = team
        self.metric = metric
        self.clause = clause
        self.interval = _resolve_interval(date_from, date_to, interval)
        self.date_from = _align_to_interval(date_from, self.interval, tzinfo=team.timezone_info)
        self.date_to = date_to

    @property
    def unit(self) -> str:
        return self.metric.unit

    def run(self) -> list[dict]:
        response = execute_hogql_query(
            query_type="DerivedMetricQuery",
            query=self._query(),
            team=self.team,
            workload=Workload.LOGS,
            settings=_QUERY_SETTINGS,
        )
        if len(response.results) >= _ROW_LIMIT:
            raise MetricQueryTooManyRowsError(
                "query produced too many (time bucket, series) rows; "
                "use a coarser interval, a narrower range, or a lower-cardinality group_by"
            )
        group_keys = [group.key for group in self.clause.group_by]
        return [
            {
                "time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0],
                "value": _finite_or_none(row[1 + len(group_keys)]),
                "labels": {key: row[1 + index] for index, key in enumerate(group_keys)},
                "series_fingerprints": [],
            }
            for row in response.results
        ]

    def _field(self, name: str, *, scope: AttributeScope = "auto") -> ast.Expr:
        column = _COLUMN_KEYS[self.metric.source].get(name)
        if column is not None:
            return ast.Field(chain=[column])
        return attribute_field(name, scope=scope)

    def _value_expr(self) -> ast.Expr:
        if self.metric.value is DerivedValue.DURATION_MS:
            duration = "duration_nano / 1e6"
            aggregation = self.clause.aggregation
            if aggregation.needs_quantile:
                assert self.clause.quantile is not None
                return parse_expr(f"quantile({float(self.clause.quantile)!r})({duration})")
            return parse_expr(f"{aggregation.value}({duration})")
        if self.clause.aggregation is MetricAggregation.RATE or self.clause.range_function is MetricRangeFunction.RATE:
            seconds = _interval_step(self.interval).total_seconds()
            return parse_expr("count() / {seconds}", placeholders={"seconds": ast.Constant(value=seconds)})
        return parse_expr("count()")

    def _predicate(self, window: ast.Expr) -> ast.Expr:
        if self.metric.source is DerivedSource.LOGS:
            return ast.Constant(value=True)
        requests = parse_expr(_REQUEST_PREDICATE, placeholders={"window": window})
        if self.metric.value is DerivedValue.ERROR_COUNT:
            return ast.And(exprs=[requests, parse_expr("status_code = 2")])
        return requests

    def _query(self) -> ast.SelectQuery:
        window = _window_expr(self.date_from, self.date_to)
        group_aliases = [f"group_{index}" for index in range(len(self.clause.group_by))]
        placeholders: dict[str, ast.Expr] = {
            "interval": _interval_expr(self.interval),
            "value": self._value_expr(),
            "window": window,
            "predicate": self._predicate(window),
            "filters": filters_expr(self.clause.filters, field_for=self._field),
            "limit": ast.Constant(value=_ROW_LIMIT),
        }
        for alias, group in zip(group_aliases, self.clause.group_by):
            placeholders[alias] = self._field(group.key, scope=group.scope.value)
        group_select = "".join(f", {{{alias}}} AS {alias}" for alias in group_aliases)
        group_by = "".join(f", {alias}" for alias in group_aliases)
        table = ".".join(str(part) for part in _TABLES[self.metric.source])
        query = parse_select(
            f"""
                SELECT toStartOfInterval(timestamp, {{interval}}) AS time{group_select}, {{value}} AS value
                FROM {table}
                WHERE {{window}} AND {{predicate}} AND {{filters}}
                GROUP BY time{group_by}
                ORDER BY time
                LIMIT {{limit}}
            """,
            placeholders=placeholders,
        )
        assert isinstance(query, ast.SelectQuery)
        return query
