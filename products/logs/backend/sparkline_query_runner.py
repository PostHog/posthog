from posthog.schema import PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunner


class SparklineQueryRunner(LogsQueryRunner):
    def _calculate(self) -> LogsQueryResponse:
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
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

        results = []
        for result in response.results:
            results.append(
                {
                    "time": result[0],
                    "level": result[1],
                    "count": result[2],
                }
            )

        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    severity_text,
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
                    WHERE time_bucket >= {date_from} and time_bucket <= toStartOfInterval({date_to} - toIntervalSecond(1), {one_interval_period})
                ) AS am
                LEFT JOIN (
                    SELECT
                        toStartOfInterval(time_bucket, {one_interval_period}) AS time,
                        severity_text,
                        count() AS event_count
                    FROM logs
                    WHERE {where} AND time >= {date_from} AND time < {date_to}
                    GROUP BY severity_text, time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, severity_text asc
                LIMIT 1000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": self.where(),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")
        return query
