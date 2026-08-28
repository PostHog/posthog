from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

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

from products.tracing.backend.duration_histogram_query_runner import duration_bucket_expr, root_scope_expr
from products.tracing.backend.logic import TraceSpansQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team


class TraceSpansLatencyHeatmapQueryRunner(TraceSpansQueryRunner):
    """Span counts per (time bucket, logarithmic duration bucket) — a latency-over-time heatmap.

    x = the sparkline's gap-filled time axis (~50 buckets), y = the duration histogram's 1-2-5
    series buckets (`duration_bucket_expr`), cell = count. Every time bucket in the window is
    enumerated: a bucket with no matching spans comes back as a single `{time, bucket_ns: 0,
    count: 0}` sentinel row, so the frontend derives the axis from the response instead of
    re-implementing the interval logic. Cells encode density only — no service breakdown.

    Root scoping matches the duration histogram: by default only root spans are bucketed (a
    distribution of traces by root duration, the row the trace list displays). When
    `query.rootSpans` is explicitly False (the operation detail page, scoped by span name),
    every matching span counts instead.
    """

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansLatencyHeatmapQuery",
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
                    "time": row[0].replace(tzinfo=ZoneInfo("UTC")).isoformat(),
                    "bucket_ns": int(row[1]),
                    "count": int(row[2]),
                }
            )

        return TraceSpansQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        # The numbers() time axis mirrors sparkline_query_runner.py — keep the bucket edges
        # identical so the two charts' x axes line up. Unlike the sparkline, the inner scan
        # groups on raw `timestamp`: the sparkline's toStartOfMinute(timestamp) trick exists to
        # hit a (minute, service) projection, which a group-by including duration buckets can
        # never use anyway. LIMIT 40 BY time caps the duration axis per column; real durations
        # (1ns–100s+) span at most ~35 of the 1-2-5 buckets.
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    ifNull(ac.bucket_ns, 0) AS bucket_ns,
                    ifNull(ac.count, 0) AS count
                FROM (
                    SELECT
                        dateAdd({date_from_start_of_interval}, {number_interval_period}) AS time_bucket
                    FROM numbers(
                        floor(
                            dateDiff({interval},
                                        {date_from_start_of_interval},
                                        {date_to_start_of_interval}) / {interval_count} + 1
                                    )
                        )
                    WHERE
                        time_bucket >= {date_from_start_of_interval} and
                        time_bucket <= greatest(
                            {date_from_start_of_interval},
                            toStartOfInterval({date_to} - toIntervalSecond(1), {one_interval_period})
                        )
                ) AS am
                LEFT JOIN (
                    SELECT
                        toStartOfInterval(timestamp, {one_interval_period}) AS time,
                        {bucket_expr} AS bucket_ns,
                        count() AS count
                    FROM posthog.trace_spans
                    WHERE {where} AND {root_scope}
                        AND time >= {date_from_start_of_interval} AND time <= {date_to}
                    GROUP BY time, bucket_ns
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time ASC, bucket_ns ASC
                LIMIT 40 BY time
                LIMIT 10000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "bucket_expr": duration_bucket_expr(),
                "where": self.where(),
                "root_scope": root_scope_expr(self.query.rootSpans),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def run_latency_heatmap_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
    root_spans: bool = True,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    """Facade-friendly entry point for running a latency heatmap query."""
    query = TraceSpansQuery(
        dateRange=date_range,
        serviceNames=service_names,
        statusCodes=status_codes,
        filterGroup=filter_group,
        rootSpans=root_spans,
    )
    runner = TraceSpansLatencyHeatmapQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
