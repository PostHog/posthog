from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CachedRevenueAnalyticsChurnRateQueryResponse,
    RevenueAnalyticsChurnRateQueryResponse,
    RevenueAnalyticsChurnRateQuery,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueAnalyticsChurnRateQueryRunner(RevenueAnalyticsQueryRunner):
    query: RevenueAnalyticsChurnRateQuery
    response: RevenueAnalyticsChurnRateQueryResponse
    cached_response: CachedRevenueAnalyticsChurnRateQueryResponse

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery.empty()

    def calculate(self):
        response = execute_hogql_query(
            query_type="revenue_analytics_churn_rate_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        assert response.results

        return RevenueAnalyticsChurnRateQueryResponse(
            results=response.results,
            modifiers=self.modifiers,
        )
