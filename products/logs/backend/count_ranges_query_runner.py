import datetime as dt
from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin

DEFAULT_TARGET_BUCKETS = 10
MAX_TARGET_BUCKETS = 100


class CountRangesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Returns adaptive-interval bucket counts for a filtered log stream.

    Each bucket carries explicit `date_from` / `date_to` so an agent can copy the
    range into a follow-up call without reasoning about interval width.
    """

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(self, *args, target_buckets: int = DEFAULT_TARGET_BUCKETS, **kwargs):
        # Set before super().__init__ so query_date_range (cached) sees the override
        # the first time it's read.
        self.BUCKET_TARGET = max(1, min(target_buckets, MAX_TARGET_BUCKETS))
        super().__init__(*args, **kwargs)

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=1_000_000_000,
            read_overflow_mode="throw",
        )

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

        ranges: list[dict] = []
        for row in response.results:
            bucket_start: dt.datetime = row[0]
            bucket_end: dt.datetime = row[1]
            count: int = row[2]
            ranges.append(
                {
                    "date_from": bucket_start.isoformat(),
                    "date_to": bucket_end.isoformat(),
                    "count": count,
                }
            )

        return LogsQueryResponse(
            results={"ranges": ranges, "interval": self._interval_short()},
        )

    def _interval_short(self) -> str:
        unit = self.query_date_range.interval_name
        count = self.query_date_range.interval_count
        if unit == "second":
            return f"{count}s"
        if unit != "minute":
            raise ValueError(f"Unexpected interval unit from picker: {unit!r} (expected 'second' or 'minute')")
        # Normalise minute counts up to hours/days when cleanly divisible.
        if count and count % 1440 == 0:
            return f"{count // 1440}d"
        if count and count % 60 == 0:
            return f"{count // 60}h"
        return f"{count}m"

    def to_query(self) -> ast.SelectQuery:
        # LogsFilterBuilder.where() filters by toStartOfDay(time_bucket) which is
        # day-precision; explicit per-row timestamp bounds (half-open) align the
        # group counts with the requested window. Same pattern as CountQueryRunner.
        where_with_timestamp = ast.And(
            exprs=[
                self.where(),
                parse_expr(
                    "timestamp >= {date_from} AND timestamp < {date_to}",
                    placeholders={
                        "date_from": ast.Constant(value=self.query_date_range.date_from()),
                        "date_to": ast.Constant(value=self.query_date_range.date_to()),
                    },
                ),
            ]
        )

        query = parse_select(
            """
                SELECT
                    toStartOfInterval(timestamp, {one_interval_period}) AS bucket_start,
                    bucket_start + {one_interval_period} AS bucket_end,
                    count() AS event_count
                FROM logs
                WHERE {where}
                GROUP BY bucket_start
                ORDER BY bucket_start ASC
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "where": where_with_timestamp,
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
