"""
Span aggregation query runners.

Two runners share a common scaffolding mixin:

- ``TraceSpansAggregationQueryRunner`` (flat): single-table ``GROUP BY (service_name,
  name)`` over a date window. One row per ``(service, name)``. Cheap enough to scan the
  full window. Used by the delta-table view.
- ``TraceSpansTreeQueryRunner`` (tree): self-join on ``(trace_id, parent_span_id)`` to
  attach parent linkage. Requires a ``spanName`` so the matched trace set is bounded —
  without that the join is prohibitive at high name cardinality. One row per
  ``(parent, child)`` edge. Used by the flame-graph view.

Both support an optional comparison window via ``compareFilter`` and run the two
windows in parallel when set.
"""

import datetime as dt
import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from posthog.schema import (
    AggregatedSpanRow,
    AttributeBreakdownRow,
    CachedTraceSpansAggregationQueryResponse,
    CachedTraceSpansTreeQueryResponse,
    DateRange,
    HogQLFilters,
    HogQLQueryModifiers,
    IntervalType,
    PropertyGroupsMode,
    SpanPropertyFilter,
    SpanPropertyFilterType,
    SpanTreeNode,
    TraceSpansAggregationQuery,
    TraceSpansAggregationQueryResponse,
    TraceSpansAttributeBreakdownQuery,
    TraceSpansTreeQuery,
    TraceSpansTreeQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.filters.mixins.utils import cached_property

from .logic import (
    TIME_BUCKET_DATE_RANGE_WHERE,
    person_scope_expr,
    translate_span_filter,
    with_span_attribute_type_suffix,
)

if TYPE_CHECKING:
    from posthog.models import Team, User


# Hard cap on number of rows returned per period. Keeps payloads bounded when name
# cardinality blows up (e.g. untemplated URL paths). The flame graph collapses long
# tails anyway so the lower-ranked rows aren't visible.
_ROW_LIMIT = 5000


class _SpanAggregationMixin:
    """Shared scaffolding for the two span aggregation runners.

    Both subclasses also inherit from ``AnalyticsQueryRunner[ResponseT]`` for their
    specific response type. This mixin assumes ``self.query`` exposes the shared fields
    (``dateRange``, ``compareFilter``, ``filterGroup``, ``serviceNames``) and that
    subclasses implement the abstract hooks below.
    """

    # Declared so the mixin's bodies type-check standalone. Subclasses redeclare `query`
    # with the narrower concrete type; the runtime attribute values come from `QueryRunner`
    # initialization on the concrete class, not from this mixin.
    if TYPE_CHECKING:
        query: TraceSpansAggregationQuery | TraceSpansTreeQuery | TraceSpansAttributeBreakdownQuery
        team: "Team"
        modifiers: HogQLQueryModifiers
        timings: HogQLTimings
        limit_context: LimitContext

    def _extract_filters(self) -> None:
        # Replicates the filter extraction the per-trace runner mixin does. We can't reuse
        # that mixin directly: it validates against TraceSpansQuery and wires a paginator
        # that does not apply here.
        self.span_filters: list[SpanPropertyFilter] = []
        self.span_attribute_filters: list[SpanPropertyFilter] = []
        self.resource_attribute_filters: list[SpanPropertyFilter] = []
        filter_group = self.query.filterGroup
        if not filter_group or not filter_group.values:
            return

        for property_group in filter_group.values:
            for prop in property_group.values:
                prop_type = getattr(prop, "type", None)
                if prop_type == SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE:
                    self.resource_attribute_filters.append(cast(SpanPropertyFilter, prop))
                elif prop_type == SpanPropertyFilterType.SPAN:
                    self.span_filters.append(cast(SpanPropertyFilter, prop))
                elif prop_type == SpanPropertyFilterType.SPAN_ATTRIBUTE:
                    if isinstance(prop, SpanPropertyFilter):
                        prop = with_span_attribute_type_suffix(prop)
                    self.span_attribute_filters.append(cast(SpanPropertyFilter, prop))

    def validate_query_runner_access(self, user: "User") -> bool:
        from posthog.rbac.user_access_control import UserAccessControlError

        raise UserAccessControlError("tracing", "viewer")

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        # Aggregation does not need the per-second interval autosizing the list view does.
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            timezone_info=ZoneInfo("UTC"),
            now=dt.datetime.now(),
        )

    def _compare_query_date_range(self) -> QueryDateRange | None:
        compare_filter = self.query.compareFilter
        if not compare_filter or not compare_filter.compare:
            return None

        if compare_filter.compare_to:
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=IntervalType.MINUTE,
                timezone_info=ZoneInfo("UTC"),
                now=dt.datetime.now(),
                compare_to=compare_filter.compare_to,
            )

        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            timezone_info=ZoneInfo("UTC"),
            now=dt.datetime.now(),
        )

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            allow_experimental_object_type=False,
            allow_experimental_join_condition=False,
            transform_null_in=False,
            max_bytes_to_read=None,
            read_overflow_mode=None,
        )

    def to_query(self) -> ast.SelectQuery:
        # Required by the AnalyticsQueryRunner base class. We default to building the
        # primary-window query here; the comparison window goes through `_run_period`.
        return self._build_query(self.query_date_range)

    def _run_with_compare(self) -> tuple[list, list | None]:
        """Run primary window, and comparison window in parallel when configured."""
        compare_range = self._compare_query_date_range()

        if compare_range is None:
            return self._run_period(self.query_date_range), None

        # Warm the person-scope expansion on this thread before dispatching the workers,
        # so its personhog RPC + config read happen once rather than racing in both.
        if self.query.personId:
            _ = self._person_scope_expr

        # Copy contextvars to worker threads so query tags (product/feature) set by the
        # viewset propagate. ThreadPoolExecutor does not inherit contextvars by default.
        primary_ctx = contextvars.copy_context()
        compare_ctx = contextvars.copy_context()

        def run_primary() -> list:
            return primary_ctx.run(self._run_period, self.query_date_range)

        def run_compare() -> list:
            return compare_ctx.run(self._run_period, compare_range)

        with ThreadPoolExecutor(max_workers=2) as pool:
            current_future = pool.submit(run_primary)
            previous_future = pool.submit(run_compare)
            return current_future.result(), previous_future.result()

    def _run_period(self, query_date_range: QueryDateRange) -> list:
        query = self._build_query(query_date_range)
        response = execute_hogql_query(
            query_type=self.query.kind,
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
            filters=HogQLFilters(
                dateRange=DateRange(
                    date_from=query_date_range.date_from().isoformat(),
                    date_to=query_date_range.date_to().isoformat(),
                )
            ),
        )
        return [self._row_from_clickhouse(row) for row in response.results]

    def _where_without_date_range(self) -> ast.Expr:
        # The base mixin's `where()` always injects its own time_bucket clause sourced
        # from `self.query_date_range`, but for the compare period we need to inject a
        # different range. We rebuild a smaller clause here that just covers filters,
        # and let `_build_query` add the time clause inline using its parameter.
        exprs: list[ast.Expr] = [ast.Placeholder(expr=ast.Field(chain=["filters"]))]

        if self.query.serviceNames:
            exprs.append(
                parse_expr(
                    "service_name IN {serviceNames}",
                    placeholders={
                        "serviceNames": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in self.query.serviceNames])
                    },
                )
            )

        if self.span_filters or self.span_attribute_filters or self.resource_attribute_filters:
            for span_filter in self.span_filters:
                translate_span_filter(span_filter)
                exprs.append(property_to_expr(span_filter, team=self.team))
            if self.span_attribute_filters:
                exprs.append(property_to_expr(self.span_attribute_filters, team=self.team))
            for resource_filter in self.resource_attribute_filters:
                exprs.append(property_to_expr(resource_filter, team=self.team))

        if self.query.personId:
            exprs.append(self._person_scope_expr)

        return ast.And(exprs=exprs)

    @cached_property
    def _person_scope_expr(self) -> ast.Expr:
        # Expanding a personId to its distinct IDs does a personhog RPC plus a
        # TeamTracingConfig read; neither changes mid-request. Cache it so the two
        # compare-window threads (see `_run_with_compare`) reuse one expansion instead
        # of each recomputing it. Only reached when `self.query.personId` is set.
        assert self.query.personId is not None
        return person_scope_expr(self.team, self.query.personId)

    # --- subclass hooks ---
    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        raise NotImplementedError

    def _row_from_clickhouse(self, row: list) -> AggregatedSpanRow | SpanTreeNode | AttributeBreakdownRow:
        raise NotImplementedError


class TraceSpansAggregationQueryRunner(_SpanAggregationMixin, AnalyticsQueryRunner[TraceSpansAggregationQueryResponse]):
    query: TraceSpansAggregationQuery
    cached_response: CachedTraceSpansAggregationQueryResponse

    def __init__(self, query: TraceSpansAggregationQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._extract_filters()

    def _calculate(self) -> TraceSpansAggregationQueryResponse:
        current_rows, previous_rows = self._run_with_compare()
        return TraceSpansAggregationQueryResponse(results=current_rows, compare=previous_rows)

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        # Single table scan plus hash aggregate. Cheap enough to run unscoped.
        query = parse_select(
            """
            SELECT
                service_name,
                name,
                count() AS count,
                sum(duration_nano) AS total_duration_nano,
                avg(duration_nano) AS avg_duration_nano,
                quantiles(0.5, 0.95, 0.99, 0.999)(duration_nano) AS duration_quantiles,
                countIf(status_code = 2) AS error_count
            FROM posthog.trace_spans
            WHERE {where}
              AND """
            + TIME_BUCKET_DATE_RANGE_WHERE
            + """
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
            GROUP BY service_name, name
            ORDER BY total_duration_nano DESC
            LIMIT {limit}
            """,
            placeholders={
                "where": self._where_without_date_range(),
                "limit": ast.Constant(value=_ROW_LIMIT),
                **query_date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _row_from_clickhouse(self, row: list) -> AggregatedSpanRow:
        p50, p95, p99, p999 = row[5] or (0.0, 0.0, 0.0, 0.0)
        return AggregatedSpanRow(
            service_name=row[0] or "",
            name=row[1] or "",
            count=row[2],
            total_duration_nano=float(row[3] or 0),
            avg_duration_nano=float(row[4] or 0),
            p50_duration_nano=float(p50 or 0),
            p95_duration_nano=float(p95 or 0),
            p99_duration_nano=float(p99 or 0),
            p999_duration_nano=float(p999 or 0),
            error_count=row[6] or 0,
        )

    def run(self, *args, **kwargs) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse)
        return response


def _annotate_calls_per_parent_invocation(rows: list[SpanTreeNode]) -> None:
    """Set each edge's child-calls-per-parent-invocation ratio, in place.

    A parent's invocation count is the sum of edge counts where it appears as the child
    (it may appear under several grandparents). Root edges have no parent invocation to
    ratio against, so they stay None.

    The denominator is reconstructed from the returned rows, so when the tree hits the
    `_ROW_LIMIT` cap a parent's child edges can be split across the cut, understating the
    denominator and overstating the ratio. That only happens with very high span-name
    cardinality in one service; the prompt doc flags the ratio as approximate at the cap.
    """
    invocations: dict[tuple[str, str], int] = {}
    for node in rows:
        key = (node.service_name, node.name)
        invocations[key] = invocations.get(key, 0) + node.count
    for node in rows:
        parent_total = invocations.get((node.parent_service, node.parent_name))
        if parent_total:
            node.calls_per_parent_invocation = node.count / parent_total


class TraceSpansTreeQueryRunner(_SpanAggregationMixin, AnalyticsQueryRunner[TraceSpansTreeQueryResponse]):
    query: TraceSpansTreeQuery
    cached_response: CachedTraceSpansTreeQueryResponse

    def __init__(self, query: TraceSpansTreeQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._extract_filters()

    def _calculate(self) -> TraceSpansTreeQueryResponse:
        current_rows, previous_rows = self._run_with_compare()
        _annotate_calls_per_parent_invocation(current_rows)
        if previous_rows is not None:
            _annotate_calls_per_parent_invocation(previous_rows)
        return TraceSpansTreeQueryResponse(results=current_rows, compare=previous_rows)

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        # The CTE has to widen the span-name filter so we can also fetch parent and
        # ancestor rows that match by trace_id but not by name; otherwise the LEFT JOIN
        # can't recover the parent. The service filter, however, is applied to the spans
        # CTE so the resulting tree is scoped to one service even when matched traces
        # span multiple services.
        query = parse_select(
            """
            WITH matched_traces AS (
                SELECT DISTINCT trace_id
                FROM posthog.trace_spans
                WHERE {where}
                  AND name = {span_name}
                  AND service_name = {service_name}
                  AND """
            + TIME_BUCKET_DATE_RANGE_WHERE
            + """
                  AND timestamp >= {date_from}
                  AND timestamp < {date_to}
            ),
            spans AS (
                SELECT
                    span_id, parent_span_id, trace_id, service_name, name,
                    duration_nano, status_code, timestamp
                FROM posthog.trace_spans
                WHERE trace_id IN (SELECT trace_id FROM matched_traces)
                  AND service_name = {service_name}
                  AND """
            + TIME_BUCKET_DATE_RANGE_WHERE
            + """
                  AND timestamp >= {date_from}
                  AND timestamp < {date_to}
            )
            SELECT
                coalesce(p.service_name, '') AS parent_service,
                if(empty(s.parent_span_id), '<ROOT>', coalesce(p.name, '<ROOT>')) AS parent_name,
                s.service_name AS service_name,
                s.name AS name,
                count() AS count,
                sum(s.duration_nano) AS total_duration_nano,
                avg(s.duration_nano) AS avg_duration_nano,
                quantiles(0.5, 0.95, 0.99, 0.999)(s.duration_nano) AS duration_quantiles,
                countIf(s.status_code = 2) AS error_count,
                avg(
                    if(
                        empty(s.parent_span_id) OR isNull(p.timestamp),
                        toFloat(0),
                        -- microsecond diff * 1000 → nanoseconds, mirroring how duration_nano is
                        -- materialized on this table. toFloat(s.timestamp) - toFloat(p.timestamp)
                        -- would give Unix *seconds* (the column is DateTime64), not nanos.
                        toFloat(dateDiff('microsecond', p.timestamp, s.timestamp) * 1000)
                    )
                ) AS avg_start_offset_nano
            FROM spans AS s
            LEFT JOIN spans AS p
                ON p.trace_id = s.trace_id AND p.span_id = s.parent_span_id
            GROUP BY parent_service, parent_name, service_name, name
            ORDER BY total_duration_nano DESC
            LIMIT {limit}
            """,
            placeholders={
                "where": self._where_without_date_range(),
                "span_name": ast.Constant(value=self.query.spanName),
                "service_name": ast.Constant(value=self.query.serviceName),
                "limit": ast.Constant(value=_ROW_LIMIT),
                **query_date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _row_from_clickhouse(self, row: list) -> SpanTreeNode:
        p50, p95, p99, p999 = row[7] or (0.0, 0.0, 0.0, 0.0)
        return SpanTreeNode(
            parent_service=row[0] or "",
            parent_name=row[1] or "<ROOT>",
            service_name=row[2] or "",
            name=row[3] or "",
            count=row[4],
            total_duration_nano=float(row[5] or 0),
            avg_duration_nano=float(row[6] or 0),
            p50_duration_nano=float(p50 or 0),
            p95_duration_nano=float(p95 or 0),
            p99_duration_nano=float(p99 or 0),
            p999_duration_nano=float(p999 or 0),
            error_count=row[8] or 0,
            avg_start_offset_nano=float(row[9] or 0),
        )

    def run(self, *args, **kwargs) -> TraceSpansTreeQueryResponse | CachedTraceSpansTreeQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansTreeQueryResponse | CachedTraceSpansTreeQueryResponse)
        return response
