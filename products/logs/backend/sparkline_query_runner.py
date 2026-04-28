from posthog.schema import LogsSparklineBreakdownBy

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunner

# Maps API breakdown type to a ClickHouse field name or HogQL expression
BREAKDOWN_DB_FIELD: dict[LogsSparklineBreakdownBy, str] = {
    LogsSparklineBreakdownBy.SEVERITY: "severity_text",
    LogsSparklineBreakdownBy.SERVICE: "service_name",
}

DEFAULT_BREAKDOWN = LogsSparklineBreakdownBy.SEVERITY


def _breakdown_expr(breakdown_by: LogsSparklineBreakdownBy) -> ast.Expr:
    if breakdown_by == LogsSparklineBreakdownBy.TRAFFIC_TYPE:
        from posthog.hogql.database.schema.traffic_type import log_user_agent_expr
        from posthog.hogql.functions.traffic_type import get_traffic_type

        return get_traffic_type(node=ast.Call(name="__placeholder", args=[]), args=[log_user_agent_expr()])

    return ast.Field(chain=[BREAKDOWN_DB_FIELD[breakdown_by]])


class SparklineQueryRunner(LogsQueryRunner):
    def _calculate(self) -> LogsQueryResponse:
        response = execute_hogql_query(
            query_type="LogsQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        result_key = (
            self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN
        ).value  # 'severity', 'service', or 'traffic_type'

        results = []
        for result in response.results:
            breakdown_value = result[1] if result[1] not in (None, "") else "(no value)"
            results.append(
                {
                    "time": result[0],
                    result_key: breakdown_value,
                    "count": result[2],
                }
            )

        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        breakdown_by = self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN
        breakdown = _breakdown_expr(breakdown_by)

        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    {breakdown_field},
                    ifNull(ac.event_count, 0) AS count
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
                        toStartOfInterval({time_field}, {one_interval_period}) AS time,
                        {breakdown_field},
                        count() AS event_count
                    FROM logs
                    WHERE {where} AND time >= {date_from_start_of_interval} AND time <= {date_to}
                    GROUP BY {breakdown_field}, time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, {breakdown_field} asc
                LIMIT 1000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                # The sparkline projection is aggregated over "toStartOfMinute(timestamp)"
                # so if we use `timestamp` we don't use the projection (even if we're calling toStartOfInterval on it)
                # explicitly use toStartOfMinute(timestamp) as the time field unless we're using a sub-minute interval
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
                "breakdown_field": breakdown,
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")
        return query
