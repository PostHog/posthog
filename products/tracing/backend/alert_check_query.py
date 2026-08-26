import time
import datetime as dt
from dataclasses import dataclass

from posthog.schema import (
    HogQLQueryResponse,
    PropertyGroupFilter,
    PropertyOperator,
    SpanPropertyFilter,
    SpanPropertyFilterType,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

from products.tracing.backend.alert_utils import MAX_BYTES_TO_READ
from products.tracing.backend.logic import (
    TIME_BUCKET_DATE_RANGE_WHERE,
    translate_span_filter,
    with_span_attribute_type_suffix,
)
from products.tracing.backend.models import TracingAlertConfiguration

# `trace_spans` lives under the `posthog.*` HogQL namespace (see
# posthog/hogql/database/database.py), unlike logs' bare `logs` table.
TRACE_SPANS_TABLE_CHAIN: list[str | int] = ["posthog", "trace_spans"]


@dataclass(frozen=True)
class AlertCheckCountResult:
    count: int
    query_duration_ms: int


@dataclass(frozen=True)
class BucketedCount:
    timestamp: dt.datetime
    count: int


def rolling_check_lookback_minutes(window_minutes: int, cadence_minutes: int, period_count: int) -> int:
    """Total minutes of history covered by M cadence-stepped rolling windows."""
    return window_minutes + (period_count - 1) * cadence_minutes


def _rolling_check_ranges(
    nca: dt.datetime,
    window_minutes: int,
    cadence_minutes: int,
    period_count: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """M cadence-stepped rolling windows ending at NCA, oldest-first."""
    ranges: list[tuple[dt.datetime, dt.datetime]] = []
    for k in range(period_count - 1, -1, -1):
        end = nca - dt.timedelta(minutes=k * cadence_minutes)
        start = end - dt.timedelta(minutes=window_minutes)
        ranges.append((start, end))
    return ranges


def _timestamp_in_range(start: dt.datetime, end: dt.datetime) -> ast.Expr:
    # Compare raw `timestamp`, not a minute-floored version: the rolling window
    # boundaries are cadence-stepped, not aligned to any coarser grid.
    return parse_expr(
        "timestamp >= {start} AND timestamp < {end}",
        placeholders={"start": ast.Constant(value=start), "end": ast.Constant(value=end)},
    )


def _tag_alert_query(*, team: Team, alert_config_id: str) -> None:
    tag_queries(
        product=Product.TRACING,
        feature=Feature.ALERTING,
        source="tracing_alert",
        alert_config_id=alert_config_id,
        team_id=str(team.id),
    )


def _property_group_filter_expr(filter_group: dict, team: Team) -> ast.Expr | None:
    """Translate a `filterGroup` payload into a WHERE expression.

    Mirrors `TraceSpansQueryRunnerMixin.where()`'s categorization loop
    (`products/tracing/backend/logic.py`) — span, span_attribute, and
    span_resource_attribute property filters — without depending on the full
    QueryRunner it's normally attached to.
    """
    pg = PropertyGroupFilter.model_validate(filter_group)
    if not pg.values:
        return None

    span_filters: list[SpanPropertyFilter] = []
    span_attribute_filters: list[SpanPropertyFilter] = []
    resource_attribute_filters: list[SpanPropertyFilter] = []
    for property_group in pg.values:
        for prop in property_group.values:
            if not isinstance(prop, SpanPropertyFilter):
                continue
            if prop.type == SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE:
                resource_attribute_filters.append(prop)
            elif prop.type == SpanPropertyFilterType.SPAN:
                span_filters.append(prop)
            elif prop.type == SpanPropertyFilterType.SPAN_ATTRIBUTE:
                span_attribute_filters.append(with_span_attribute_type_suffix(prop))

    exprs: list[ast.Expr] = []
    for span_filter in span_filters:
        translate_span_filter(span_filter)
        exprs.append(property_to_expr(span_filter, team=team))
    if span_attribute_filters:
        exprs.append(property_to_expr(span_attribute_filters, team=team))
    for resource_filter in resource_attribute_filters:
        exprs.append(property_to_expr(resource_filter, team=team))

    if not exprs:
        return None
    return exprs[0] if len(exprs) == 1 else ast.And(exprs=exprs)


def build_alert_where_expr(
    *,
    team: Team,
    alert: TracingAlertConfiguration,
    date_from: dt.datetime,
    date_to: dt.datetime,
) -> ast.Expr:
    """Build the per-alert WHERE expression against `trace_spans`.

    Filters follow `TracingAlertConfiguration.filters`' documented shape
    (`serviceNames`, `errorOnly`, `filterGroup`).
    """
    filters = alert.filters
    exprs: list[ast.Expr] = [
        # `time_bucket` day-range bound first for partition/primary-key pruning,
        # mirroring `LogsFilterBuilder.where()`.
        parse_expr(
            TIME_BUCKET_DATE_RANGE_WHERE,
            placeholders={"date_from": ast.Constant(value=date_from), "date_to": ast.Constant(value=date_to)},
        ),
        _timestamp_in_range(date_from, date_to),
    ]

    if service_names := filters.get("serviceNames"):
        exprs.append(
            parse_expr(
                "service_name IN {serviceNames}",
                placeholders={"serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in service_names])},
            )
        )

    if filters.get("errorOnly"):
        error_filter = SpanPropertyFilter(
            key="status_code",
            operator=PropertyOperator.EXACT,
            type=SpanPropertyFilterType.SPAN,
            value="Error",
        )
        translate_span_filter(error_filter)
        exprs.append(property_to_expr(error_filter, team=team))

    if filter_group := filters.get("filterGroup"):
        if expr := _property_group_filter_expr(filter_group, team):
            exprs.append(expr)

    return ast.And(exprs=exprs)


class AlertCheckQuery:
    """Lightweight count query against `trace_spans` for alert checks.

    Mirrors `products/logs/backend/alert_check_query.py`'s `AlertCheckQuery` —
    own timeout/byte limits, not an `AnalyticsQueryRunner`, since this runs on a
    schedule rather than in response to a user request.

    v1 intentionally omits the batched multi-alert query and projection fast path
    that logs' `AlertCheckQuery` added once its alert volume outgrew per-alert
    queries — `trace_spans` has no equivalent alert-oriented projection yet.
    Tracing alerting is expected to need the same optimizations on a similar
    timeline as logs did, not only if volume happens to warrant it later.
    """

    SETTINGS = HogQLGlobalSettings(
        max_execution_time=30,
        max_bytes_to_read=MAX_BYTES_TO_READ,
        read_overflow_mode="throw",
    )

    def __init__(
        self,
        *,
        team: Team,
        alert: TracingAlertConfiguration,
        date_from: dt.datetime,
        date_to: dt.datetime,
    ) -> None:
        if alert.team_id != team.id:
            raise ValueError(f"Alert {alert.id} belongs to team {alert.team_id}, not {team.id}")
        self.team = team
        self.alert = alert
        self.date_from = date_from
        self.date_to = date_to
        self.where_expr = build_alert_where_expr(team=team, alert=alert, date_from=date_from, date_to=date_to)

    def execute(self) -> AlertCheckCountResult:
        """Return a single aggregate count for the alert window."""
        self._tag()

        # Same ast.SelectQuery/ast.JoinExpr construction as execute_rolling_checks(),
        # rather than a parsed SQL string, so both methods build `FROM trace_spans`
        # through TRACE_SPANS_TABLE_CHAIN the same way.
        query = ast.SelectQuery(
            select=[ast.Alias(alias="total", expr=ast.Call(name="count", args=[]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=TRACE_SPANS_TABLE_CHAIN)),
            where=self.where_expr,
        )

        start_ms = time.monotonic_ns() // 1_000_000
        response = self._run_query(query)
        duration_ms = time.monotonic_ns() // 1_000_000 - start_ms

        count = response.results[0][0] if response.results else 0
        return AlertCheckCountResult(count=count, query_duration_ms=duration_ms)

    def execute_rolling_checks(
        self,
        nca: dt.datetime,
        window_minutes: int,
        cadence_minutes: int,
        period_count: int,
    ) -> list[BucketedCount]:
        """Per-check counts for M cadence-stepped rolling windows ending at NCA, oldest-first."""
        self._tag()
        ranges = _rolling_check_ranges(nca, window_minutes, cadence_minutes, period_count)

        select_columns: list[ast.Expr] = [
            ast.Alias(
                alias=f"period_{i}",
                expr=ast.Call(name="countIf", args=[_timestamp_in_range(start, end)]),
            )
            for i, (start, end) in enumerate(ranges)
        ]
        query = ast.SelectQuery(
            select=select_columns,
            select_from=ast.JoinExpr(table=ast.Field(chain=TRACE_SPANS_TABLE_CHAIN)),
            where=self.where_expr,
        )
        response = self._run_query(query)
        row = response.results[0] if response.results else [0] * len(ranges)
        return [BucketedCount(timestamp=start, count=count) for (start, _), count in zip(ranges, row)]

    def _run_query(self, query: ast.SelectQuery | ast.SelectSetQuery) -> HogQLQueryResponse:
        if not isinstance(query, ast.SelectQuery):
            raise ValueError("Failed to build alert check query")

        return execute_hogql_query(
            query_type="alert_check",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
            settings=self.SETTINGS,
            limit_context=LimitContext.QUERY,
        )

    def _tag(self) -> None:
        _tag_alert_query(team=self.team, alert_config_id=str(self.alert.id))
