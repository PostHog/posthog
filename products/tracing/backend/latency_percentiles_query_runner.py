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
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import ExecutionMode

from products.tracing.backend.logic import TraceSpansQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team


# The environment key the APM services API groups by, so the fallback below splits spans the same way.
_ENVIRONMENT = (
    "coalesce(nullIf(resource_attributes['deployment.environment.name'], ''), "
    "nullIf(resource_attributes['deployment.environment'], ''), nullIf(resource_attributes['env'], ''), "
    "nullIf(resource_attributes['k8s.cluster.name'], ''), '')"
)


class TraceSpansLatencyPercentilesQueryRunner(TraceSpansQueryRunner):
    """p50, p95 and p99 span duration per time bucket, on the sparkline's time axis.

    The spans are a service's requests as the APM services API counts them: server and consumer
    spans, or root spans for a service and environment that has neither in the window. The
    quantiles use the same ClickHouse function as that API's p95, so a bucket's line agrees with
    the summary over it.
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

        results = []
        for time, count, p50, p95, p99 in response.results:
            count = int(count)
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
        # The innermost scan keeps quantile states per (bucket, service, environment). The window
        # sum then picks entry or root spans per service and environment over the whole window,
        # as the services API does, before the states merge into one line per bucket.
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    ifNull(ac.count, 0) AS count,
                    arrayElement(ac.quantiles, 1) AS p50,
                    arrayElement(ac.quantiles, 2) AS p95,
                    arrayElement(ac.quantiles, 3) AS p99
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
                        time,
                        sum(if(use_entry, entry_count, root_count)) AS count,
                        quantilesMerge(0.5, 0.95, 0.99)(if(use_entry, entry_quantiles, root_quantiles)) AS quantiles
                    FROM (
                        SELECT
                            *,
                            sum(entry_count) OVER (PARTITION BY service_name, environment) > 0 AS use_entry
                        FROM (
                            SELECT
                                toStartOfInterval(timestamp, {one_interval_period}) AS time,
                                service_name,
                                {environment} AS environment,
                                countIf(kind IN (2, 5)) AS entry_count,
                                quantilesStateIf(0.5, 0.95, 0.99)(duration_nano, kind IN (2, 5)) AS entry_quantiles,
                                countIf(is_root_span) AS root_count,
                                quantilesStateIf(0.5, 0.95, 0.99)(duration_nano, is_root_span) AS root_quantiles
                            FROM posthog.trace_spans
                            WHERE {where} AND (kind IN (2, 5) OR is_root_span)
                                AND timestamp >= {date_from} AND timestamp < {date_to}
                            GROUP BY time, service_name, environment
                        )
                    )
                    GROUP BY time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time ASC
                LIMIT 1000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "environment": parse_expr(_ENVIRONMENT),
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
    status_codes: list[int] | None = None,
    filter_group: PropertyGroupFilter | None = None,
) -> TraceSpansQueryResponse | CachedTraceSpansQueryResponse:
    query = TraceSpansQuery(
        dateRange=date_range, serviceNames=service_names, statusCodes=status_codes, filterGroup=filter_group
    )
    runner = TraceSpansLatencyPercentilesQueryRunner(query, team)
    response = runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
    assert isinstance(response, TraceSpansQueryResponse | CachedTraceSpansQueryResponse)
    return response
