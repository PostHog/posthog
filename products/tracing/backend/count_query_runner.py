from typing import TYPE_CHECKING

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    DateRange,
    PropertyGroupFilter,
    TraceSpansQuery,
    TraceSpansQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode

from products.tracing.backend.logic import TraceSpansScalarQueryRunnerMixin

if TYPE_CHECKING:
    from posthog.models import Team


class TraceSpansCountQueryRunner(TraceSpansScalarQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    """Returns a scalar count of trace spans matching the given filters.

    Cheap pre-flight before query-apm-spans: lets a caller size the result set before
    pulling rows. Reuses the shared filter builder so the count matches what the list query
    would select."""

    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse

    def _calculate(self) -> TraceSpansQueryResponse:
        results = self.execute()
        count = results[0][0] if results else 0
        trace_count = results[0][1] if results else 0
        return TraceSpansQueryResponse(results={"count": count, "traceCount": trace_count})

    def to_query(self) -> ast.SelectQuery:
        # count() is every matching span (the "Spans" view's row count). The trace count must match the
        # "Traces" view, which selects traces by root-span match (rootSpans defaults True -> root_only in
        # logic.py), so restrict the distinct-trace count to matching root spans, not any matching span.
        query = parse_select(
            "SELECT count(), uniqExactIf(trace_id, is_root_span = 1) FROM posthog.trace_spans WHERE {where}",
            placeholders={"where": self.where_with_exact_timestamps()},
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
