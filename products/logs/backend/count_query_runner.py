from functools import cached_property

from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin


class CountQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Returns a scalar count of log entries matching the given filters."""

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    @cached_property
    def settings(self) -> HogQLGlobalSettings:
        # A count should fail fast rather than scan unbounded data. Matches the
        # caps AlertCheckQuery uses against the same table.
        return HogQLGlobalSettings(
            max_execution_time=30,
            max_bytes_to_read=10_000_000_000,
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
        count = response.results[0][0] if response.results else 0
        return LogsQueryResponse(results={"count": count})

    def to_query(self) -> ast.SelectQuery:
        # LogsFilterBuilder.where() filters by toStartOfDay(time_bucket) which is
        # day-precision; adding explicit per-row timestamp bounds (half-open to
        # avoid double-counting on boundaries) makes the count match the requested
        # window. Same pattern as AlertCheckQuery.
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
            "SELECT count() FROM logs WHERE {where}",
            placeholders={"where": where_with_timestamp},
        )
        assert isinstance(query, ast.SelectQuery)
        return query
