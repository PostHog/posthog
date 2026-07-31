from zoneinfo import ZoneInfo

from posthog.schema import LogsSparklineBreakdownBy

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models.filters.mixins.utils import cached_property

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunner

# Maps API breakdown type to ClickHouse field name
BREAKDOWN_DB_FIELD: dict[LogsSparklineBreakdownBy, str] = {
    LogsSparklineBreakdownBy.SEVERITY: "severity_text",
    LogsSparklineBreakdownBy.SERVICE: "service_name",
}

DEFAULT_BREAKDOWN = LogsSparklineBreakdownBy.SEVERITY

# The volume preview must return quickly or fail clearly. Its bytes breakdown sums
# `_bytes_uncompressed`, which the minute-aggregate projection doesn't cover, so a
# high-volume service can fall back to a full table scan. Cap execution well below the
# 60s default so a slow preview surfaces an error promptly instead of appearing to hang.
SPARKLINE_PREVIEW_MAX_EXECUTION_SECONDS = 30


class SparklineQueryRunner(LogsQueryRunner):
    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # Inherit LogsQueryRunner's distributed-logs settings — including the
        # allow_experimental_object_type / allow_experimental_join_condition / transform_null_in
        # bug-workaround flags it sets to False — and only tighten the execution timeout. Building
        # a fresh HogQLGlobalSettings here would silently re-enable those buggy defaults.
        return super().settings.model_copy(update={"max_execution_time": SPARKLINE_PREVIEW_MAX_EXECUTION_SECONDS})

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
            breakdown_value = result[1] if result[1] not in (None, "") else "(no value)"
            results.append(
                {
                    # Tag the bucket time as UTC so it serializes with an offset, matching the log
                    # row timestamp and the live_logs_checkpoint the frontend compares it against.
                    "time": result[0].replace(tzinfo=ZoneInfo("UTC")) if result[0] else result[0],
                    result_key: breakdown_value,
                    "count": result[2],
                    "bytes_uncompressed": result[3],
                }
            )

        return LogsQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    {breakdown_field},
                    ifNull(ac.event_count, 0) AS count,
                    ifNull(ac.bytes_uncompressed, 0) AS bytes_uncompressed
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
                        count() AS event_count,
                        sum(_bytes_uncompressed) AS bytes_uncompressed
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
                "breakdown_field": ast.Field(
                    chain=[BREAKDOWN_DB_FIELD[self.query.sparklineBreakdownBy or DEFAULT_BREAKDOWN]]
                ),
            },
        )
        if not isinstance(query, ast.SelectQuery):
            raise Exception("NO!")
        return query
