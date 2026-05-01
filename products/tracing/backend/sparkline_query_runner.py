from zoneinfo import ZoneInfo

from posthog.schema import TraceSpansQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload

from products.tracing.backend.logic import TraceSpansQueryRunner


class TraceSpansSparklineQueryRunner(TraceSpansQueryRunner):
    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansSparklineQuery",
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
                    "service": row[1],
                    "count": row[2],
                }
            )

        return TraceSpansQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
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
                    FROM posthog.trace_spans
                    WHERE {where} AND time >= {date_from_start_of_interval} AND time <= {date_to}
                    GROUP BY {breakdown_field}, time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, count desc
                LIMIT 10 BY time LIMIT 10000
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
                "breakdown_field": ast.Field(chain=["service_name"]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
