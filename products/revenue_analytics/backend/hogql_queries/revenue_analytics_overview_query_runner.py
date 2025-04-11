from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsOverviewQuery,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsOverviewQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsOverviewQuery
    response: RevenueAnalyticsOverviewQueryResponse
    cached_response: CachedRevenueAnalyticsOverviewQueryResponse

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery.empty()

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_overview_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert response.results

        return RevenueAnalyticsOverviewQueryResponse(
            results=response.results,
            modifiers=self.modifiers,
        )
