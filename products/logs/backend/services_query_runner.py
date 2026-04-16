from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin


class ServicesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Returns per-service aggregates (volume, error count, error rate) and sparkline data."""

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def _calculate(self) -> LogsQueryResponse:
        aggregates_response = execute_hogql_query(
            query_type="LogsQuery",
            query=self._aggregates_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        sparkline_response = execute_hogql_query(
            query_type="LogsQuery",
            query=self._sparkline_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        services = []
        for row in aggregates_response.results:
            service_name = row[0] if row[0] else "(no service)"
            log_count = row[1]
            error_count = row[2]
            error_rate = error_count / log_count if log_count > 0 else 0.0
            services.append(
                {
                    "service_name": service_name,
                    "log_count": log_count,
                    "error_count": error_count,
                    "error_rate": round(error_rate, 4),
                }
            )

        sparkline = []
        for row in sparkline_response.results:
            sparkline.append(
                {
                    "time": row[0],
                    "service_name": row[1] if row[1] else "(no service)",
                    "count": row[2],
                }
            )

        return LogsQueryResponse(results={"services": services, "sparkline": sparkline})

    def to_query(self) -> ast.SelectQuery:
        return self._aggregates_query()

    def _aggregates_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                service_name,
                sum(_log_count) AS log_count,
                sumIf(_log_count, in(severity_text, tuple('error', 'fatal'))) AS error_count
            FROM (
                SELECT
                    service_name,
                    count() AS _log_count,
                    severity_text,
                FROM logs
                WHERE {where}
                GROUP BY service_name, severity_text
            )
            GROUP BY service_name
            ORDER BY log_count DESC
            LIMIT 25
            """,
            placeholders={
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _sparkline_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                toStartOfInterval({time_field}, {one_interval_period}) AS time,
                service_name,
                count() AS event_count
            FROM logs
            WHERE {where}
            GROUP BY service_name, time
            ORDER BY time ASC, service_name ASC
            LIMIT 10000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
