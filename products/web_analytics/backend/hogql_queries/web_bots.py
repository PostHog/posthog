from posthog.schema import (
    CachedWebBotsTableQueryResponse,
    WebBotsBreakdown,
    WebBotsTableQuery,
    WebBotsTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator

from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner

# Events bots are detected on. Mirrors BOT_ANALYTICS_EVENTS in
# frontend/src/scenes/web-analytics/common.ts — $http_log covers server-side
# crawler hits that never execute the JS snippet.
BOT_ANALYTICS_EVENTS = ("$pageview", "$screen", "$http_log")

DEFAULT_LIMIT = 50


class WebBotsTableQueryRunner(WebAnalyticsQueryRunner[WebBotsTableQueryResponse]):
    query: WebBotsTableQuery
    cached_response: CachedWebBotsTableQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit or DEFAULT_LIMIT
        )

    def to_query(self) -> ast.SelectQuery:
        if self.query.breakdownBy == WebBotsBreakdown.PATH:
            template = """
SELECT
    properties.$pathname AS "Path",
    count(DISTINCT `$virt_bot_name`) AS "Crawlers",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE and(
    `$virt_is_bot` = true,
    `$virt_bot_name` != '',
    event IN {bot_events},
    properties.$pathname IS NOT NULL,
    {inside_timestamp_period},
    {all_properties},
)
GROUP BY "Path"
ORDER BY "Requests" DESC
"""
        else:
            template = """
SELECT
    `$virt_bot_name` AS "Crawler",
    `$virt_traffic_category` AS "Category",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE and(
    `$virt_is_bot` = true,
    `$virt_bot_name` != '',
    event IN {bot_events},
    {inside_timestamp_period},
    {all_properties},
)
GROUP BY "Crawler", "Category"
ORDER BY "Requests" DESC
"""
        with self.timings.measure("web_bots_query"):
            query = parse_select(
                template,
                timings=self.timings,
                placeholders={
                    "bot_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in BOT_ANALYTICS_EVENTS]),
                    "inside_timestamp_period": self._periods_expression("timestamp"),
                    "all_properties": self._all_properties(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _all_properties(self) -> ast.Expr:
        properties = self.query.properties + self._test_account_filters
        return property_to_expr(properties, team=self.team)

    def _calculate(self):
        query = self.to_query()
        response = self.paginator.execute_hogql_query(
            query_type="web_bots_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        results = self.paginator.results
        assert results is not None

        return WebBotsTableQueryResponse(
            columns=response.columns,
            results=[list(row) for row in results],
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
