"""Derived metrics: series that a query computes from spans and logs.

A derived metric reads the existing `trace_spans` and `logs` rows and writes nothing,
so it adds no storage and no metrics ingestion. Saved insights keep the metric name,
so a later ingestion-time rollup can serve the same names without changes for users.
"""

import datetime as dt
from collections.abc import Callable, Iterable, Sequence
from enum import StrEnum
from functools import partial

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.parallel import run_in_parallel_threads
from posthog.models import Team
from posthog.scopes.catalog import APIScopeObject

from products.metrics.backend.facade.contracts import (
    DERIVED_METRIC_PREFIX,
    METRICS_DERIVED_SERIES_FEATURE_FLAG,
    MetricFilter,
    MetricQueryClause,
    MetricQueryTooManyRowsError,
)
from products.metrics.backend.facade.enums import (
    AttributeScope as LabelScope,
    FilterOp,
    MetricAggregation,
    MetricRangeFunction,
    MetricType,
)
from products.metrics.backend.metric_query_runner import (
    _SERVICE_NAME_KEYS,
    AttributeScope,
    _align_to_interval,
    _finite_or_none,
    _interval_expr,
    _interval_step,
    _resolve_interval,
    attribute_field,
    filters_expr,
)
from products.metrics.backend.search import ilike_pattern

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
_AUTOCOMPLETE_WINDOW = dt.timedelta(hours=24)
# Autocomplete tolerates partial results, so a read stops at the budget instead of failing.
_AUTOCOMPLETE_SETTINGS = HogQLGlobalSettings(
    max_execution_time=10,
    max_bytes_to_read=10_000_000_000,
    read_overflow_mode="break",
)
_DATA_PRESENCE_CACHE_TTL_SECONDS = 300
# An empty or partly failed answer is held briefly: new spans or logs show up within a minute,
# and a caller that polls does not re-run the probes on every request.
_DATA_PRESENCE_RECHECK_TTL_SECONDS = 60
# A probe reads at most one row, so a slow one means ClickHouse is struggling: give up early.
_PRESENCE_QUERY_SETTINGS = HogQLGlobalSettings(
    max_execution_time=10,
    max_bytes_to_read=10_000_000_000,
    read_overflow_mode="throw",
)


class DerivedSource(StrEnum):
    SPANS = "spans"
    LOGS = "logs"


class DerivedValue(StrEnum):
    COUNT = "count"
    ERROR_COUNT = "error_count"
    DURATION_MS = "duration_ms"
    APDEX = "apdex"


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
        name=f"{DERIVED_METRIC_PREFIX}spans.apdex",
        source=DerivedSource.SPANS,
        value=DerivedValue.APDEX,
        metric_type=MetricType.GAUGE,
        unit="1",
        description=(
            "Apdex score from 0 to 1: satisfied requests plus half the tolerating ones, over all requests. "
            "A request is satisfied at or under the threshold T (500 ms unless the query sets it), "
            "tolerating up to 4T, and frustrated above that or when it errors."
        ),
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

# The keys the filter bar suggests for a derived metric: what request and latency charts slice by.
_PICKER_KEYS: dict[DerivedSource, tuple[str, ...]] = {
    DerivedSource.SPANS: (
        "service.name",
        "span.name",
        "span.kind",
        "span.status_code",
        "deployment.environment",
        "service.version",
        "http.route",
        "http.status_code",
    ),
    DerivedSource.LOGS: ("service.name", "severity_text"),
}

_DERIVED_METRICS_BY_NAME: dict[str, DerivedMetric] = {metric.name: metric for metric in DERIVED_METRICS}

# The access-control resource and API scope object that guard each source.
SOURCE_RESOURCES: dict[DerivedSource, APIScopeObject] = {
    DerivedSource.SPANS: "tracing",
    DerivedSource.LOGS: "logs",
}

_TABLES: dict[DerivedSource, list[str | int]] = {
    DerivedSource.SPANS: ["posthog", "trace_spans"],
    DerivedSource.LOGS: ["logs"],
}

# Keys that map to a column. Other keys read the attribute maps, as for ingested metrics.
_COLUMN_KEYS: dict[DerivedSource, dict[str, str]] = {
    DerivedSource.SPANS: {"span.name": "name"},
    DerivedSource.LOGS: {"severity_text": "severity_text"},
}

# Span columns that store an OTel enum as an int. Grouping and filtering use the enum's name,
# so `span.kind = server` matches and a chart legend reads "server", not "2".
_ENUM_COLUMN_KEYS: dict[DerivedSource, dict[str, tuple[str, tuple[str, ...]]]] = {
    DerivedSource.SPANS: {
        "span.kind": ("kind", ("unspecified", "internal", "server", "client", "producer", "consumer")),
        "span.status_code": ("status_code", ("unset", "ok", "error")),
    },
    DerivedSource.LOGS: {},
}

# The viewer sends NONE for a counter that the user has not aggregated yet. A derived counter has one
# value per bucket, so NONE gives the same count as SUM.
_COUNTER_AGGREGATIONS = frozenset(
    {MetricAggregation.NONE, MetricAggregation.SUM, MetricAggregation.INCREASE, MetricAggregation.RATE}
)
_HISTOGRAM_AGGREGATIONS = frozenset(
    {
        MetricAggregation.QUANTILE,
        MetricAggregation.HISTOGRAM_QUANTILE,
        MetricAggregation.AVG,
        MetricAggregation.MIN,
        MetricAggregation.MAX,
    }
)

# Apdex is one score per bucket, so these all return it unchanged.
_APDEX_AGGREGATIONS = frozenset({MetricAggregation.NONE, MetricAggregation.AVG})
DEFAULT_APDEX_THRESHOLD_MS = 500.0

# A request is a server span. A service that has no server spans in the window counts its root
# spans, so a consumer's client spans count once each. This matches the APM service health.
# `service_filters` keeps the fallback in the selected environment, as APM service health does.
_REQUEST_PREDICATE = """
    (kind = 2 OR (is_root_span AND service_name NOT IN (
        SELECT DISTINCT service_name FROM posthog.trace_spans WHERE {window} AND kind = 2 AND {service_filters}
    )))
"""

# Filters on these keys select services or environments, not single spans.
_SERVICE_SCOPE_KEYS = frozenset(
    {"service.name", "service_name", "deployment.environment", "deployment.environment.name", "env"}
)


def _source_field(source: DerivedSource, name: str, *, scope: AttributeScope = "auto") -> ast.Expr:
    column = _COLUMN_KEYS[source].get(name)
    if column is not None:
        return ast.Field(chain=[column])
    enum_column = _ENUM_COLUMN_KEYS[source].get(name)
    if enum_column is not None:
        column, labels = enum_column
        return parse_expr(
            "transform({column}, {codes}, {labels}, toString({column}))",
            placeholders={
                "column": ast.Field(chain=[column]),
                "codes": ast.Array(exprs=[ast.Constant(value=code) for code in range(len(labels))]),
                "labels": ast.Array(exprs=[ast.Constant(value=label) for label in labels]),
            },
        )
    return attribute_field(name, scope=scope)


def _picker_field(source: DerivedSource, name: str) -> ast.Expr:
    """`_source_field` for the key and value pickers, with bare reads of the physical attribute maps.

    The span and log `attributes` column aliases a `mapApply` over all of `attributes_map_str`, and a
    property-group read adds a `has()` guard that reads every map bucket. A bare `arrayElement` on the
    physical map reads only the bucket that holds the key. A missing key reads as ''.
    """
    if name in _COLUMN_KEYS[source] or name in _ENUM_COLUMN_KEYS[source] or name in _SERVICE_NAME_KEYS:
        return _source_field(source, name)
    # Explicit calls, so the resolver does not fold the reads back into property chains.
    resource = ast.Call(name="arrayElement", args=[ast.Field(chain=["resource_attributes"]), ast.Constant(value=name)])
    attribute = ast.Call(
        name="arrayElement", args=[ast.Field(chain=["attributes_map_str"]), ast.Constant(value=f"{name}__str")]
    )
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(op=ast.CompareOperationOp.NotEq, left=resource, right=ast.Constant(value="")),
            resource,
            attribute,
        ],
    )


def is_derived_metric_name(name: str) -> bool:
    return name.startswith(DERIVED_METRIC_PREFIX)


def derived_metric_resources(names: Iterable[str]) -> list[APIScopeObject]:
    """The access-control resources whose data the derived metrics among `names` read."""
    return sorted(
        {SOURCE_RESOURCES[_DERIVED_METRICS_BY_NAME[name].source] for name in names if name in _DERIVED_METRICS_BY_NAME}
    )


def get_derived_metric(name: str) -> DerivedMetric:
    metric = _DERIVED_METRICS_BY_NAME.get(name)
    if metric is None:
        known = ", ".join(sorted(_DERIVED_METRICS_BY_NAME))
        raise ValueError(f"Unknown derived metric {name!r}. Derived metrics: {known}")
    return metric


def derived_metrics_enabled(team: Team) -> bool:
    # The flag is an experiment with `control` and `test` variants, so only `test` (or a plain boolean
    # rollout) turns derived series on. The flag splits by organization, so the distinct ID does not
    # change the variant.
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    try:
        variant = posthoganalytics.get_feature_flag(
            METRICS_DERIVED_SERIES_FEATURE_FLAG,
            str(team.uuid),
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("metrics_derived_series_flag_check_failed", team_id=team.id)
        return False
    return variant is True or variant == "test"


def team_has_derived_sources(team: Team, *, can_read: Callable[[APIScopeObject], bool]) -> bool:
    """True when the team sent spans or logs in the last day from a source the caller can read."""
    return any(can_read(SOURCE_RESOURCES[source]) for source in _sources_with_data(team))


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
    failed: list[DerivedSource] = []

    def probe(source: DerivedSource, table: list[str | int]) -> None:
        query = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(table=ast.Field(chain=table)),
            where=window,
            limit=ast.Constant(value=1),
        )
        # A failed check hides that source's names, but the picker still lists the other names.
        try:
            response = execute_hogql_query(
                query_type="DerivedMetricsPresenceQuery",
                query=query,
                team=team,
                workload=Workload.LOGS,
                settings=_PRESENCE_QUERY_SETTINGS,
            )
        except Exception:
            logger.warning("metrics_derived_presence_check_failed", team_id=team.id, source=source.value, exc_info=True)
            failed.append(source)
            return
        if response.results:
            sources.add(source)

    work: list[Callable[[], None]] = [partial(probe, source, table) for source, table in _TABLES.items()]
    # The probes do not depend on each other, so the caller waits for the slowest, not their sum.
    # Django does not make the test transaction visible to another thread.
    if settings.IN_UNIT_TESTING:
        for item in work:
            item()
    else:
        run_in_parallel_threads(
            [partial(_closing_connection, item) for item in work], thread_name_prefix="metrics_derived_presence"
        )

    complete = bool(sources) and not failed
    cache.set(
        cache_key,
        sorted(sources),
        _DATA_PRESENCE_CACHE_TTL_SECONDS if complete else _DATA_PRESENCE_RECHECK_TTL_SECONDS,
    )
    return sources


def _closing_connection(work: Callable[[], None]) -> None:
    try:
        work()
    finally:
        # The query reads Postgres in the worker thread, possibly through a replica alias, and request cleanup
        # only closes the request thread's connections.
        connections.close_all()


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
        if metric.value is DerivedValue.APDEX:
            if clause.aggregation not in _APDEX_AGGREGATIONS:
                raise ValueError(f"{metric.name} supports the avg aggregation")
            if clause.range_function is not None:
                raise ValueError(f"{metric.name} does not support a range function")
        elif metric.metric_type is MetricType.HISTOGRAM:
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
        return _source_field(self.metric.source, name, scope=scope)

    def _value_expr(self) -> ast.Expr:
        if self.metric.value is DerivedValue.APDEX:
            threshold_ms = self.clause.apdex_threshold_ms or DEFAULT_APDEX_THRESHOLD_MS
            # Errors are frustrated whatever their duration.
            return parse_expr(
                """
                (countIf(status_code != 2 AND duration_nano <= {t})
                    + countIf(status_code != 2 AND duration_nano > {t} AND duration_nano <= {t4}) / 2) / count()
                """,
                placeholders={
                    "t": ast.Constant(value=threshold_ms * 1e6),
                    "t4": ast.Constant(value=4 * threshold_ms * 1e6),
                },
            )
        if self.metric.value is DerivedValue.DURATION_MS:
            duration = parse_expr("duration_nano / 1e6")
            aggregation = self.clause.aggregation
            if aggregation.needs_quantile:
                assert self.clause.quantile is not None
                return ast.Call(
                    name="quantile", params=[ast.Constant(value=float(self.clause.quantile))], args=[duration]
                )
            return ast.Call(name=aggregation.value, args=[duration])
        # Errors count over the request rows, so a service without errors keeps a zero bucket.
        count = (
            parse_expr("countIf(status_code = 2)")
            if self.metric.value is DerivedValue.ERROR_COUNT
            else parse_expr("count()")
        )
        if self.clause.aggregation is MetricAggregation.RATE or self.clause.range_function is MetricRangeFunction.RATE:
            seconds = _interval_step(self.interval).total_seconds()
            return parse_expr(
                "{count} / {seconds}", placeholders={"count": count, "seconds": ast.Constant(value=seconds)}
            )
        return count

    def _predicate(self, window: ast.Expr) -> ast.Expr:
        if self.metric.source is DerivedSource.LOGS:
            return ast.Constant(value=True)
        service_filters = [
            f for f in self.clause.filters if f.scope is LabelScope.RESOURCE or f.key in _SERVICE_SCOPE_KEYS
        ]
        return parse_expr(
            _REQUEST_PREDICATE,
            placeholders={"window": window, "service_filters": self._filters(service_filters)},
        )

    def _filters(self, filters: Sequence[MetricFilter]) -> ast.Expr:
        if not filters:
            return ast.Constant(value=True)
        conditions = [self._enum_condition(f) or filters_expr([f], field_for=self._field) for f in filters]
        return conditions[0] if len(conditions) == 1 else ast.And(exprs=conditions)

    def _enum_condition(self, filter: MetricFilter) -> ast.Expr | None:
        # Compare the int column directly, so the column's minmax index can still skip granules.
        enum_column = _ENUM_COLUMN_KEYS[self.metric.source].get(filter.key)
        if enum_column is None or filter.op not in (FilterOp.EQ, FilterOp.NEQ):
            return None
        column, labels = enum_column
        if filter.value in labels:
            code = labels.index(filter.value)
        elif filter.value.isdigit():
            code = int(filter.value)
        else:
            return None
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq if filter.op == FilterOp.EQ else ast.CompareOperationOp.NotEq,
            left=ast.Field(chain=[column]),
            right=ast.Constant(value=code),
        )

    def _query(self) -> ast.SelectQuery:
        window = _window_expr(self.date_from, self.date_to)
        group_aliases = [f"group_{index}" for index in range(len(self.clause.group_by))]
        placeholders: dict[str, ast.Expr] = {
            "interval": _interval_expr(self.interval),
            "value": self._value_expr(),
            "window": window,
            "predicate": self._predicate(window),
            "filters": self._filters(self.clause.filters),
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


@frozen
class _AutocompleteWindow:
    date_from: dt.datetime
    date_to: dt.datetime


def _autocomplete_window(date_from: dt.datetime | None, date_to: dt.datetime | None) -> _AutocompleteWindow:
    resolved_to = date_to or timezone.now()
    resolved_from = date_from or resolved_to - _AUTOCOMPLETE_WINDOW
    if resolved_to <= resolved_from:
        raise ValueError("date_to must be after date_from")
    return _AutocompleteWindow(date_from=resolved_from, date_to=resolved_to)


def list_derived_attribute_keys(
    team: Team,
    *,
    metric_name: str,
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """The filter and group-by keys for a derived metric that have values in the window,
    most distinct values first, as `{"name", "value_count"}` dicts."""
    source = get_derived_metric(metric_name).source
    needle = search.strip().lower()
    keys = [key for key in _PICKER_KEYS[source] if needle in key.lower()]
    if not keys:
        return []
    window = _autocomplete_window(date_from, date_to)
    counts = [
        parse_expr(
            "uniqIf(toString({field}), toString({field}) != '')", placeholders={"field": _picker_field(source, key)}
        )
        for key in keys
    ]
    query = ast.SelectQuery(
        select=counts,
        select_from=ast.JoinExpr(table=ast.Field(chain=_TABLES[source])),
        where=_window_expr(window.date_from, window.date_to),
    )
    response = execute_hogql_query(
        query_type="DerivedMetricAttributeKeysQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_AUTOCOMPLETE_SETTINGS,
    )
    row = response.results[0] if response.results else [0] * len(keys)
    found = sorted(((key, int(count)) for key, count in zip(keys, row) if count), key=lambda pair: -pair[1])
    return [{"name": key, "value_count": count} for key, count in found[:limit]]


def list_derived_attribute_values(
    team: Team,
    *,
    metric_name: str,
    key: str,
    search: str = "",
    date_from: dt.datetime | None = None,
    date_to: dt.datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    """Observed values of one key for a derived metric, most frequent first, as `{"id", "name", "count"}` dicts."""
    source = get_derived_metric(metric_name).source
    window = _autocomplete_window(date_from, date_to)
    table = ".".join(str(part) for part in _TABLES[source])
    query = parse_select(
        f"""
            SELECT toString({{field}}) AS value, count() AS occurrences
            FROM {table}
            WHERE {{window}} AND value != '' AND value ILIKE {{pattern}}
            GROUP BY value
            ORDER BY occurrences DESC, value
            LIMIT {{limit}}
        """,
        placeholders={
            "field": _picker_field(source, key),
            "window": _window_expr(window.date_from, window.date_to),
            "pattern": ast.Constant(value=ilike_pattern(search.strip())),
            "limit": ast.Constant(value=limit),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    response = execute_hogql_query(
        query_type="DerivedMetricAttributeValuesQuery",
        query=query,
        team=team,
        workload=Workload.LOGS,
        settings=_AUTOCOMPLETE_SETTINGS,
    )
    return [{"id": value, "name": value, "count": count} for value, count in response.results]
