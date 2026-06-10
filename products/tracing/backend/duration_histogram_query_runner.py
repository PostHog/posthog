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
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import ExecutionMode

from products.tracing.backend.logic import TraceSpansQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team


class TraceSpansDurationHistogramQueryRunner(TraceSpansQueryRunner):
    """Trace counts per logarithmic duration bucket, stacked by service.

    Feeds the sparkline when the span list is sorted by duration: x = 1-2-5 series duration
    buckets (1ms, 2ms, 5ms, 10ms, ...), bars = count of traces whose ROOT span falls in the
    bucket (the root is the row the list displays), grouped by service. Only non-empty buckets
    are returned; the frontend fills gaps along the series so the axis is continuous.

    Root scoping is unconditional — `query.rootSpans` is deliberately ignored. The histogram is a
    distribution of *traces*; counting child spans would mix units. The 1-2-5 bucketing below is
    mirrored in `frontend/durationBuckets.ts` (snapDurationToBucket), which re-snaps client-side
    only to place the scroll highlight — change the series in BOTH places.
    """

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansDurationHistogramQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        results = []
        for row in response.results:
            results.append(
                {
                    "bucket_ns": int(row[0]),
                    "service": row[1],
                    "count": row[2],
                }
            )

        return TraceSpansQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        # Bucket a duration onto the 1-2-5 series: take its decade (power of ten) and snap the
        # mantissa down to 1, 2 or 5. `greatest(..., 1)` parks zero-duration spans in the 1ns
        # bucket instead of feeding log10(0). The mantissa expression repeats the decade rather
        # than referencing its alias so HogQL resolution never depends on sibling aliases;
        # ClickHouse collapses the common subexpression. `round()` before the cast absorbs float
        # wobble in pow/log10 (e.g. 4.9999...e8 → 5e8).
        query = parse_select(
            """
            SELECT
                toInt(round(
                    pow(10, floor(log10(greatest(duration_nano, 1)))) * multiIf(
                        duration_nano / pow(10, floor(log10(greatest(duration_nano, 1)))) < 2, 1,
                        duration_nano / pow(10, floor(log10(greatest(duration_nano, 1)))) < 5, 2,
                        5
                    )
                )) AS bucket_ns,
                service_name AS service,
                count() AS count
            FROM posthog.trace_spans
            WHERE {where}
                AND is_root_span = 1
                AND timestamp >= {date_from} AND timestamp < {date_to}
            GROUP BY bucket_ns, service
            ORDER BY bucket_ns ASC, count DESC
            LIMIT 10 BY bucket_ns
            LIMIT 10000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def run_duration_histogram_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Facade-friendly entry point for running a duration histogram query."""
    query = TraceSpansQuery(
        dateRange=date_range,
        serviceNames=service_names,
        statusCodes=status_codes,
        filterGroup=filter_group,
    )
    runner = TraceSpansDurationHistogramQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
