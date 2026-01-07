from posthog.schema import LogsSparklineBreakdownBy

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunner

# Maps API breakdown type to ClickHouse field name
BREAKDOWN_DB_FIELD: dict[LogsSparklineBreakdownBy, str] = {
    LogsSparklineBreakdownBy.SEVERITY: "severity_text",
    LogsSparklineBreakdownBy.SERVICE: "service_name",
}

DEFAULT_BREAKDOWN = LogsSparklineBreakdownBy.SEVERITY


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

        result_key = (self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN).value  # 'severity' or 'service'

        results = []
        for result in response.results:
            breakdown_value = result[1]
            if breakdown_value == "$$_other_$$":
                breakdown_value = "Other"
            elif breakdown_value in (None, "", "$$_no_value_$$"):
                breakdown_value = "(no value)"
            results.append(
                {
                    "time": result[0],
                    result_key: breakdown_value,
                    "count": result[2],
                }
            )

        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    time,
                    if(global_rank <= 10, breakdown_value, '$$_other_$$') AS breakdown_bucket,
                    sum(event_count) AS count
                FROM (
                    SELECT
                        bucket_data.time AS time,
                        bucket_data.breakdown_value AS breakdown_value,
                        bucket_data.event_count AS event_count,
                        global_ranks.global_rank AS global_rank
                    FROM (
                        SELECT
                            am.time_bucket AS time,
                            ifNull({breakdown_field}, '$$_no_value_$$') AS breakdown_value,
                            ifNull(ac.event_count, 0) AS event_count
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
                            WHERE {where}
                              AND timestamp >= {date_from_start_of_interval}
                              AND timestamp <= {date_to}
                            GROUP BY {breakdown_field}, time
                        ) AS ac ON am.time_bucket = ac.time
                    ) AS bucket_data
                    LEFT JOIN (
                        SELECT
                            ifNull({breakdown_field}, '$$_no_value_$$') AS breakdown_value,
                            row_number() OVER (ORDER BY count() DESC) AS global_rank
                        FROM logs
                        WHERE {where}
                          AND timestamp >= {date_from_start_of_interval}
                          AND timestamp <= {date_to}
                        GROUP BY breakdown_value
                    ) AS global_ranks ON bucket_data.breakdown_value = global_ranks.breakdown_value
                )
                GROUP BY time, breakdown_bucket
                ORDER BY time ASC, breakdown_bucket ASC
                LIMIT 100000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "time_field": ast.Field(chain=["time_minute"])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
                "breakdown_field": ast.Field(
                    chain=[BREAKDOWN_DB_FIELD[self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN]]
                ),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")
        return query
