from zoneinfo import ZoneInfo

from posthog.schema import HogQLFilters, TraceSpansQueryResponse

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
            filters=HogQLFilters(dateRange=self.query.dateRange),
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
                toStartOfFiveMinutes(timestamp) AS bucket,
                service_name,
                count() AS count
            FROM posthog.trace_spans
            WHERE {where} AND is_root_span = 1
            GROUP BY bucket, service_name
            ORDER BY bucket ASC
            """,
            placeholders={"where": self.where()},
        )
        assert isinstance(query, ast.SelectQuery)
        return query
