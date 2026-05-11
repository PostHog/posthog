"""
Aggregation query runner for trace spans.

Groups spans by (parent_service, parent_name, service_name, name) over a date
window and computes count, total/avg/p50/p95 duration, and error count. When a
`compareFilter` is set, runs a second query for the comparison window in parallel
and returns both result sets.
"""

import datetime as dt
import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from posthog.schema import (
    AggregatedSpanRow,
    CachedTraceSpansAggregationQueryResponse,
    CompareFilter,
    DateRange,
    HogQLFilters,
    IntervalType,
    PropertyGroupFilter,
    PropertyGroupsMode,
    SpanPropertyFilter,
    SpanPropertyFilterType,
    TraceSpansAggregationQuery,
    TraceSpansAggregationQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.filters.mixins.utils import cached_property

if TYPE_CHECKING:
    from posthog.models import Team, User


# Hard cap on number of (parent, child) groups returned per period. Keeps payloads
# bounded when name cardinality blows up (e.g. untemplated URL paths). The flame
# graph collapses long tails anyway so the lower-ranked rows aren't visible.
_AGGREGATION_ROW_LIMIT = 5000


class TraceSpansAggregationQueryRunner(AnalyticsQueryRunner[TraceSpansAggregationQueryResponse]):
    query: TraceSpansAggregationQuery
    cached_response: CachedTraceSpansAggregationQueryResponse

    def __init__(self, query: TraceSpansAggregationQuery, *args, **kwargs) -> None:
        super().__init__(query, *args, **kwargs)

        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED

        # Replicate the filter-extraction the per-trace runner mixin does. We can't reuse
        # that mixin directly: it forces super().__init__() to validate against TraceSpansQuery
        # and sets up a paginator that does not apply to aggregation queries.
        def get_property_type(value: str | float | bool) -> str:
            try:
                float(value)
                return "float"
            except (ValueError, TypeError):
                pass
            return "str"

        self.span_filters: list[SpanPropertyFilter] = []
        self.span_attribute_filters: list[SpanPropertyFilter] = []
        self.resource_attribute_filters: list[SpanPropertyFilter] = []
        if query.filterGroup and query.filterGroup.values:
            for property_group in query.filterGroup.values:
                for prop in property_group.values:
                    prop_type = getattr(prop, "type", None)
                    if prop_type == SpanPropertyFilterType.SPAN_RESOURCE_ATTRIBUTE:
                        self.resource_attribute_filters.append(prop)
                    elif prop_type == SpanPropertyFilterType.SPAN:
                        self.span_filters.append(prop)
                    elif prop_type == SpanPropertyFilterType.SPAN_ATTRIBUTE:
                        if isinstance(prop, SpanPropertyFilter) and prop.value:
                            property_type = "str"
                            if isinstance(prop.value, list):
                                property_types = {get_property_type(v) for v in prop.value}
                                if len(property_types) == 1:
                                    property_type = property_types.pop()
                            else:
                                property_type = get_property_type(prop.value)

                            prop = prop.model_copy(deep=True)
                            prop.key = f"{prop.key}__{property_type}"

                        self.span_attribute_filters.append(prop)

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
                now=dt.datetime.now(),
                compare_to=compare_filter.compare_to,
            )

        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=IntervalType.MINUTE,
            now=dt.datetime.now(),
        )

    def _calculate(self) -> TraceSpansAggregationQueryResponse:
        compare_range = self._compare_query_date_range()
        mode = "tree" if self.is_tree_mode else "flat"

        if compare_range is None:
            current_rows = self._run_period(self.query_date_range)
            return TraceSpansAggregationQueryResponse(results=current_rows, mode=mode)

        # Copy contextvars to the worker threads so query tags (product/feature) set by the
        # viewset propagate. ThreadPoolExecutor does not inherit contextvars by default.
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=2) as pool:
            current_future = pool.submit(ctx.run, self._run_period, self.query_date_range)
            previous_future = pool.submit(contextvars.copy_context().run, self._run_period, compare_range)
            current_rows = current_future.result()
            previous_rows = previous_future.result()

        return TraceSpansAggregationQueryResponse(results=current_rows, compare=previous_rows, mode=mode)

    def _run_period(self, query_date_range: QueryDateRange) -> list[AggregatedSpanRow]:
        query = self._build_query(query_date_range)
        response = execute_hogql_query(
            query_type="TraceSpansAggregationQuery",
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

        return [
            AggregatedSpanRow(
                parent_service=row[0] or "",
                parent_name=row[1] or "<ROOT>",
                service_name=row[2] or "",
                name=row[3] or "",
                count=row[4],
                total_duration_nano=float(row[5] or 0),
                avg_duration_nano=float(row[6] or 0),
                p50_duration_nano=float(row[7] or 0),
                p95_duration_nano=float(row[8] or 0),
                error_count=row[9] or 0,
                avg_start_offset_nano=float(row[10] or 0),
            )
            for row in response.results
        ]

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

    @cached_property
    def is_tree_mode(self) -> bool:
        """Return True if the caller scoped the query to a specific span name.

        The flame-graph (tree) view requires a self-join on `(trace_id, parent_span_id)`
        which becomes prohibitive at high cardinality. We only run that path when the
        caller has filtered to a span name — that bounds the data and the join becomes
        tractable. Without the filter we fall through to a flat aggregation per
        (service, name), which is what the delta table on the front end consumes.
        """
        for span_filter in self.span_filters:
            if span_filter.key == "name":
                return True
        return False

    def _build_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        if self.is_tree_mode:
            return self._build_tree_query(query_date_range)
        return self._build_flat_query(query_date_range)

    def _build_flat_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        # No self-join: flat GROUP BY (service_name, name) over the window. Roughly the
        # same shape as the existing sparkline runner — single table scan plus hash
        # aggregate. This is the path used by the unfiltered delta-table view.
        query = parse_select(
            """
            SELECT
                '' AS parent_service,
                '<ROOT>' AS parent_name,
                service_name,
                name,
                count() AS count,
                sum(duration_nano) AS total_duration_nano,
                avg(duration_nano) AS avg_duration_nano,
                quantile(0.5)(duration_nano) AS p50_duration_nano,
                quantile(0.95)(duration_nano) AS p95_duration_nano,
                countIf(status_code = 2) AS error_count,
                toFloat(0) AS avg_start_offset_nano
            FROM posthog.trace_spans
            WHERE {where}
              AND toStartOfDay(time_bucket) >= toStartOfDay({date_from})
              AND toStartOfDay(time_bucket) <= toStartOfDay({date_to})
              AND timestamp >= {date_from}
              AND timestamp < {date_to}
            GROUP BY service_name, name
            ORDER BY total_duration_nano DESC
            LIMIT {limit}
            """,
            placeholders={
                "where": self._where_without_date_range(),
                "limit": ast.Constant(value=_AGGREGATION_ROW_LIMIT),
                **query_date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _build_tree_query(self, query_date_range: QueryDateRange) -> ast.SelectQuery:
        # The tree query only runs when scoped to a span name. The CTE has to widen the
        # span-name filter so we can also fetch parent and ancestor rows that match by
        # trace_id but not by name; otherwise the LEFT JOIN can't recover the parent.
        query = parse_select(
            """
            WITH matched_traces AS (
                SELECT DISTINCT trace_id
                FROM posthog.trace_spans
                WHERE {where}
                  AND toStartOfDay(time_bucket) >= toStartOfDay({date_from})
                  AND toStartOfDay(time_bucket) <= toStartOfDay({date_to})
                  AND timestamp >= {date_from}
                  AND timestamp < {date_to}
            ),
            spans AS (
                SELECT
                    span_id, parent_span_id, trace_id, service_name, name,
                    duration_nano, status_code, timestamp
                FROM posthog.trace_spans
                WHERE trace_id IN (SELECT trace_id FROM matched_traces)
                  AND toStartOfDay(time_bucket) >= toStartOfDay({date_from})
                  AND toStartOfDay(time_bucket) <= toStartOfDay({date_to})
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
                quantile(0.5)(s.duration_nano) AS p50_duration_nano,
                quantile(0.95)(s.duration_nano) AS p95_duration_nano,
                countIf(s.status_code = 2) AS error_count,
                avg(
                    if(
                        empty(s.parent_span_id) OR isNull(p.timestamp),
                        toFloat(0),
                        toFloat(toUnixTimestamp(s.timestamp) - toUnixTimestamp(p.timestamp))
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
                "limit": ast.Constant(value=_AGGREGATION_ROW_LIMIT),
                **query_date_range.to_placeholders(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _where_without_date_range(self) -> ast.Expr:
        # The base mixin's `where()` always injects its own time_bucket clause sourced
        # from `self.query_date_range`, but for the compare period we need to inject a
        # different range. We rebuild a smaller clause here that just covers filters,
        # and let `_build_query` add the time clause inline using its parameter.
        from posthog.hogql.parser import parse_expr

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
            from posthog.hogql.property import property_to_expr

            for span_filter in self.span_filters:
                exprs.append(property_to_expr(span_filter, team=self.team))
            if self.span_attribute_filters:
                exprs.append(property_to_expr(self.span_attribute_filters, team=self.team))
            for resource_filter in self.resource_attribute_filters:
                exprs.append(property_to_expr(resource_filter, team=self.team))

        return ast.And(exprs=exprs)

    def run(self, *args, **kwargs) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
        response = super().run(*args, **kwargs)
        assert isinstance(response, TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse)
        return response


def run_aggregation_query(
    *,
    team: "Team",
    date_range: DateRange,
    compare_filter: CompareFilter | None = None,
    filter_group: PropertyGroupFilter | None = None,
    service_names: list[str] | None = None,
) -> TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse:
    """Facade-friendly entry point for running a span aggregation query."""
    from posthog.hogql_queries.query_runner import ExecutionMode

    query = TraceSpansAggregationQuery(
        dateRange=date_range,
        compareFilter=compare_filter,
        filterGroup=filter_group,
        serviceNames=service_names,
    )
    runner = TraceSpansAggregationQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansAggregationQueryResponse | CachedTraceSpansAggregationQueryResponse)
    return response
