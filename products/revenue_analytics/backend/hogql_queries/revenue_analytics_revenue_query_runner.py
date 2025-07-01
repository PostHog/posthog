from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQuery,
    QueryDateRangeResponse,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsRevenueQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsRevenueQuery
    response: RevenueAnalyticsRevenueQueryResponse
    cached_response: CachedRevenueAnalyticsRevenueQueryResponse

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery.empty()

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_revenue_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        return RevenueAnalyticsRevenueQueryResponse(
            results=response.results,
            hogql=response.hogql,
            modifiers=self.modifiers,
            query_date_range=QueryDateRangeResponse(
                date_from=self.query_date_range.date_from(),
                date_to=self.query_date_range.date_to(),
                interval=self.query_date_range.interval_type,
            ),
        )
