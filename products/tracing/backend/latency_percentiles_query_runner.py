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

from products.tracing.backend.logic import TraceSpansQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team


class TraceSpansLatencyPercentilesQueryRunner(TraceSpansQueryRunner):
    """p50, p95 and p99 span duration per time bucket, on the sparkline's time axis.

    The spans are a service's requests as the APM services API counts them: server and consumer
    spans, or root spans when the matching spans hold neither. The quantiles use the same
    ClickHouse function as that API's p95, so a bucket's line agrees with the summary over it.
    """

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansLatencyPercentilesQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        rows = response.results
        use_entry = any(int(row[1]) > 0 for row in rows)
        results = []
        for time, entry_count, *entry_quantiles, root_count, root_p50, root_p95, root_p99 in rows:
            count = int(entry_count if use_entry else root_count)
            p50, p95, p99 = entry_quantiles if use_entry else (root_p50, root_p95, root_p99)
            results.append(
                {
                    "time": time.replace(tzinfo=ZoneInfo("UTC")).isoformat(),
                    "count": count,
                    "p50_ns": int(p50) if count else None,
                    "p95_ns": int(p95) if count else None,
                    "p99_ns": int(p99) if count else None,
                }
            )
        return TraceSpansQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        # The numbers() axis mirrors latency_heatmap_query_runner.py, so the charts' x axes line up.
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    ifNull(ac.entry_count, 0) AS entry_count,
                    ac.entry_p50 AS entry_p50,
                    ac.entry_p95 AS entry_p95,
                    ac.entry_p99 AS entry_p99,
                    ifNull(ac.root_count, 0) AS root_count,
                    ac.root_p50 AS root_p50,
                    ac.root_p95 AS root_p95,
                    ac.root_p99 AS root_p99
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
                        countIf(kind IN (2, 5)) AS entry_count,
                        quantileIf(0.5)(duration_nano, kind IN (2, 5)) AS entry_p50,
                        quantileIf(0.95)(duration_nano, kind IN (2, 5)) AS entry_p95,
                        quantileIf(0.99)(duration_nano, kind IN (2, 5)) AS entry_p99,
                        countIf(is_root_span) AS root_count,
                        quantileIf(0.5)(duration_nano, is_root_span) AS root_p50,
                        quantileIf(0.95)(duration_nano, is_root_span) AS root_p95,
                        quantileIf(0.99)(duration_nano, is_root_span) AS root_p99
                    FROM posthog.trace_spans
                    WHERE {where} AND (kind IN (2, 5) OR is_root_span)
                        AND time >= {date_from_start_of_interval} AND time <= {date_to}
                    GROUP BY time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time ASC
                LIMIT 1000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def run_latency_percentiles_query(
    *,
    team: "Team",
    date_range: DateRange,
    service_names: list[str] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    query = TraceSpansQuery(dateRange=date_range, serviceNames=service_names, filterGroup=filter_group)
    runner = TraceSpansLatencyPercentilesQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
