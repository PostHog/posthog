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
from functools import cached_property
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from posthog.schema import (
    AggregatedSpanRow,
    AttributeBreakdownRow,
    CachedTraceSpansAggregationQueryResponse,
    CachedTraceSpansTreeQueryResponse,
    HogQLQueryModifiers,
    IntervalType,
    PropertyGroupsMode,
    SpanHealthStatus,
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
from posthog.hogql_queries.utils.caller_context import map_in_caller_context
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange

# _ROW_LIMIT lives in logic.py so the presentation layer can reach it through the
# facade-allowed `logic` module; imported here (and re-exported) for the sibling runners.
from .logic import (
    _ROW_LIMIT,
    TIME_BUCKET_DATE_RANGE_WHERE,
    translate_span_filter,
    with_attribute_set_guards,
    with_span_attribute_type_suffix,
)
from .models import TracingIdentityAttributeKeys
from .service_health_query_runner import ServiceWindowStats, classify_service
from .span_identity import identity_value_expr, str_attr_field

if TYPE_CHECKING:
    from posthog.models import Team, User


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
        from products.access_control.backend.facade.user_access_control import UserAccessControlError

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
            return self._run_period(self.query_date_range, self.timings), None

        # HogQLTimings is not thread safe, so each worker gets its own clone.
        windows = [
            (self.query_date_range, self.timings.clone_for_subquery(0)),
            (compare_range, self.timings.clone_for_subquery(1)),
        ]

        def run_window(window: tuple[QueryDateRange, HogQLTimings]) -> list:
            return self._run_period(*window)

        current, previous = map_in_caller_context(run_window, windows, thread_name_prefix="tracing_aggregation")
        for _, timings in windows:
            self.timings.timings.update(timings.timings)
        return current, previous

    def _run_period(self, query_date_range: QueryDateRange, timings: HogQLTimings) -> list:
        query = self._build_query(query_date_range)
        response = execute_hogql_query(
            query_type=self.query.kind,
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=timings,
            limit_context=self.limit_context,
            settings=self.settings,
            filters=query_date_range.to_hogql_filters(),
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
                exprs.append(property_to_expr(with_attribute_set_guards(self.span_attribute_filters), team=self.team))
            for resource_filter in with_attribute_set_guards(self.resource_attribute_filters):
                exprs.append(property_to_expr(resource_filter, team=self.team))

        return ast.And(exprs=exprs)

    # --- subclass hooks ---
    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        raise NotImplementedError

    def _row_from_clickhouse(self, row: list) -> AggregatedSpanRow | SpanTreeNode | AttributeBreakdownRow:
        raise NotImplementedError


class TraceSpansAggregationQueryRunner(_SpanAggregationMixin, AnalyticsQueryRunner[TraceSpansAggregationQueryResponse]):
    query: TraceSpansAggregationQuery
    cached_response: CachedTraceSpansAggregationQueryResponse

    def __init__(
        self,
        query: TraceSpansAggregationQuery,
        *args,
        limit: int | None = None,
        offset: int = 0,
        identity_keys: TracingIdentityAttributeKeys | None = None,
        **kwargs,
    ) -> None:
        super().__init__(query, *args, **kwargs)
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self._extract_filters()
        self._limit = _ROW_LIMIT if limit is None else max(1, min(limit, _ROW_LIMIT))
        self._offset = max(0, offset)
        self._identity_keys = identity_keys
        self._baseline_keys: list[tuple[str, str]] | None = None

    def get_cache_payload(self) -> dict:
        # Runner arguments, not query fields, so the base payload cannot see them.
        return {**super().get_cache_payload(), "limit": self._limit, "offset": self._offset}

    def _compare_query_date_range(self) -> QueryDateRange | None:
        compare_range = super()._compare_query_date_range()
        if compare_range is None and self.query.includeHealth:
            # Health needs a baseline, so without a comparison it uses the previous period.
            return QueryPreviousPeriodDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=IntervalType.MINUTE,
                timezone_info=ZoneInfo("UTC"),
                now=dt.datetime.now(),
            )
        return compare_range

    def _run_with_compare(self) -> tuple[list, list | None]:
        if not self.query.includeHealth:
            return super()._run_with_compare()
        compare_range = self._compare_query_date_range()
        assert compare_range is not None
        # Sequential: the baseline reads only the current page's rows, because their rank in the baseline can differ.
        current_rows = self._run_period(self.query_date_range, self.timings)
        if not current_rows:
            return current_rows, []
        self._baseline_keys = [(row.service_name, row.name) for row in current_rows]
        return current_rows, self._run_period(compare_range, self.timings)

    def _calculate(self) -> TraceSpansAggregationQueryResponse:
        current_rows, previous_rows = self._run_with_compare()
        if self.query.includeHealth:
            self._classify(current_rows, previous_rows or [])
            if not (self.query.compareFilter and self.query.compareFilter.compare):
                previous_rows = None
        return TraceSpansAggregationQueryResponse(results=current_rows, compare=previous_rows)

    def _classify(self, current_rows: list[AggregatedSpanRow], baseline_rows: list[AggregatedSpanRow]) -> None:
        # shortcut: rows carry no last-seen time, so silent never fires. Add a last_seen column if per-endpoint
        # silence detection is needed.
        baseline = {(row.service_name, row.name): row for row in baseline_rows}
        window_from = self.query_date_range.date_from()
        window_to = min(self.query_date_range.date_to(), dt.datetime.now(tz=ZoneInfo("UTC")))
        for row in current_rows:
            before = baseline.get((row.service_name, row.name))
            status, reason = classify_service(
                current=_window_stats(row, window_to),
                baseline=_window_stats(before, window_to) if before else None,
                has_baseline=True,
                window_from=window_from,
                window_to=window_to,
            )
            row.health_status = SpanHealthStatus(status.value)
            row.health_reason = reason

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        # Single table scan plus hash aggregate. Cheap enough to run unscoped.
        where = self._where_without_date_range()
        group_name: ast.Expr = ast.Field(chain=["name"])
        if self.query.groupByEndpoint:
            where = ast.And(exprs=[where, _endpoint_scope_expr()])
            group_name = _endpoint_name_expr()
        limit, offset = self._limit, self._offset
        if self._baseline_keys is not None and query_date_range is not self.query_date_range:
            keys = ast.Tuple(
                exprs=[
                    ast.Tuple(exprs=[ast.Constant(value=service), ast.Constant(value=name)])
                    for service, name in self._baseline_keys
                ]
            )
            where = ast.And(
                exprs=[
                    where,
                    parse_expr(
                        "tuple(service_name, {group_name}) IN {keys}",
                        placeholders={"keys": keys, "group_name": group_name},
                    ),
                ]
            )
            limit, offset = len(self._baseline_keys), 0
        placeholders: dict[str, ast.Expr] = {
            "where": where,
            "group_name": group_name,
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
            **query_date_range.to_placeholders(),
        }
        # Appended rather than always present, because reading the attribute maps is the
        # expensive part of this query and only the Operations columns need it. uniq() is
        # HyperLogLog-based and skips NULLs. `_row_from_clickhouse` reads these by position.
        impact_columns = ""
        if self.query.includeImpact:
            if self._identity_keys is None:
                raise ValueError("includeImpact requires identity_keys")
            placeholders["session_value"] = identity_value_expr(self._identity_keys.session)
            placeholders["person_value"] = identity_value_expr(self._identity_keys.distinct_id)
            impact_columns = """,
                uniq({session_value}) AS sessions,
                uniq({person_value}) AS users,
                count({session_value}) AS spans_with_session_id,
                count({person_value}) AS spans_with_distinct_id"""

        query = parse_select(
            """
            SELECT
                service_name,
                {group_name} AS group_name,
                count() AS count,
                sum(duration_nano) AS total_duration_nano,
                avg(duration_nano) AS avg_duration_nano,
                quantiles(0.5, 0.95, 0.99, 0.999)(duration_nano) AS duration_quantiles,
                countIf(status_code = 2) AS error_count"""
            + impact_columns
            + """
            FROM posthog.trace_spans
            WHERE {where}
              AND """
            + TIME_BUCKET_DATE_RANGE_WHERE
            + """
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
            GROUP BY service_name, group_name
            ORDER BY total_duration_nano DESC
            LIMIT {limit}
            OFFSET {offset}
            """,
            placeholders=placeholders,
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _row_from_clickhouse(self, row: list) -> AggregatedSpanRow:
        p50, p95, p99, p999 = row[5] or (0.0, 0.0, 0.0, 0.0)
        with_impact = self.query.includeImpact
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
            sessions=row[7] if with_impact else None,
            users=row[8] if with_impact else None,
            spans_with_session_id=row[9] if with_impact else None,
            spans_with_distinct_id=row[10] if with_impact else None,
        )

    def run(self, *args, **kwargs) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse)
        return response


def _window_stats(row: AggregatedSpanRow, last_seen: dt.datetime) -> ServiceWindowStats:
    return ServiceWindowStats(
        requests=row.count,
        errors=row.error_count,
        p50_ms=row.p50_duration_nano / 1e6,
        p95_ms=row.p95_duration_nano / 1e6,
        p99_ms=row.p99_duration_nano / 1e6,
        last_seen=last_seen,
    )


def _http_method_expr() -> ast.Expr:
    # OTel renamed `http.method` to `http.request.method`; SDKs in the wild send either.
    return parse_expr(
        "coalesce(nullIf({new}, ''), nullIf({old}, ''))",
        placeholders={"new": str_attr_field("http.request.method"), "old": str_attr_field("http.method")},
    )


def _endpoint_scope_expr() -> ast.Expr:
    # Server spans alone include queue consumers and Temporal activities, which carry no HTTP method.
    return parse_expr("kind = 2 AND {method} IS NOT NULL", placeholders={"method": _http_method_expr()})


def _endpoint_name_expr() -> ast.Expr:
    # Instrumentations may name a span after the raw path or the bare method, so the route is the stable key.
    return parse_expr(
        "if({route} IS NOT NULL, concat({method}, ' ', {route}), name)",
        placeholders={
            "route": ast.Call(name="nullIf", args=[str_attr_field("http.route"), ast.Constant(value="")]),
            "method": _http_method_expr(),
        },
    )


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
