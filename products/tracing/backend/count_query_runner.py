from functools import cached_property
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    DateRange,
    HogQLFilters,
    PropertyGroupFilter,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode

from products.tracing.backend.logic import TraceSpansQueryRunnerMixin

if TYPE_CHECKING:
    from posthog.models import Team


class TraceSpansCountQueryRunner(TraceSpansQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    """Returns a scalar count of trace spans matching the given filters.

    Cheap pre-flight before query-apm-spans: lets a caller size the result set before
    pulling rows. Reuses the shared filter builder so the count matches what the list query
    would select."""

    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # A count should fail fast rather than scan unbounded data — matches the caps the
        # logs count runner uses against the same kind of table.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
            read_overflow_mode="throw",
        )

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            filters=HogQLFilters(dateRange=self.query.dateRange),
            settings=self.settings,
        )
        count = response.results[0][0] if response.results else 0
        trace_count = response.results[0][1] if response.results else 0
        return TraceSpansQueryResponse(results={"count": count, "traceCount": trace_count})

    def to_query(self) -> ast.SelectQuery:
        # where() bounds the window by time_bucket (day precision); add explicit half-open
        # per-row timestamp bounds so the count matches the requested window exactly.
        where_with_timestamp = ast.And(
            exprs=[
                self.where(),
                parse_expr(
                    "timestamp >= {date_from} AND timestamp < {date_to}",
                    placeholders={
                        "date_from": ast.Constant(value=self.query_date_range.date_from()),
                        "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    },
                ),
            ]
        )
        # count() is every matching span (the "Spans" view's row count). The trace count must match the
        # "Traces" view, which selects traces by root-span match (rootSpans defaults True → root_only in
        # logic.py), so restrict the distinct-trace count to matching root spans — not any matching span.
        query = parse_select(
            "SELECT count(), uniqExactIf(trace_id, is_root_span = 1) FROM posthog.trace_spans WHERE {where}",
            placeholders={"where": where_with_timestamp},
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def run_count_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Facade-friendly entry point for running a span count query."""
    query = TraceSpansQuery(
        dateRange=date_range,
        serviceNames=service_names,
        statusCodes=status_codes,
        filterGroup=filter_group,
    )
    runner = TraceSpansCountQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
