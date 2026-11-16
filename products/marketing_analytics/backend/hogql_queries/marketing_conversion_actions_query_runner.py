from datetime import datetime
from functools import cached_property

from posthog.schema import (
    CachedMarketingAnalyticsConversionActionsQueryResponse,
    DateRange,
    MarketingAnalyticsConversionAction,
    MarketingAnalyticsConversionActionsQuery,
    MarketingAnalyticsConversionActionsQueryResponse,
    MarketingAnalyticsRecommendationsSource,
    MarketingAnalyticsRecommendationsSourceType,
)

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.recommendation_sources_query_runner import (
    RecommendationSourcesQueryRunner,
)

CONVERSION_ACTION_WINDOW_DAYS = 90


class MarketingAnalyticsConversionActionsQueryRunner(
    RecommendationSourcesQueryRunner[MarketingAnalyticsConversionActionsQueryResponse]
):
    hogql_query_type = "marketing_analytics_conversion_actions_query"
    query: MarketingAnalyticsConversionActionsQuery
    response: MarketingAnalyticsConversionActionsQueryResponse
    cached_response: CachedMarketingAnalyticsConversionActionsQueryResponse

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=DateRange(date_from=f"-{CONVERSION_ACTION_WINDOW_DAYS}d"),
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    @cached_property
    def saved_actions(self) -> list[str]:
        return list(self.team.marketing_analytics_config.recommendation_conversion_actions or [])

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        payload["saved_actions"] = self.saved_actions
        return payload

    def _calculate(self) -> MarketingAnalyticsConversionActionsQueryResponse:
        sources = self.query.sources if self.query.sources is not None else self._project_sources()
        results = [
            action
            for source in sources
            if source.sourceType == MarketingAnalyticsRecommendationsSourceType.GOOGLE_ADS
            for action in self._account_actions(source)
        ]
        listed = {action.action for action in results}
        return MarketingAnalyticsConversionActionsQueryResponse(
            results=results,
            unmatchedSavedActions=[action for action in self.saved_actions if action not in listed],
        )

    def _account_actions(
        self, source: MarketingAnalyticsRecommendationsSource
    ) -> list[MarketingAnalyticsConversionAction]:
        table = source.campaignConversionActionTable
        if not self._readable(table) or not source.campaignTable:
            return []
        assert table
        name = self._field(table, "segments_conversion_action_name")
        category = self._field(table, "segments_conversion_action_category")
        rows = self._select(
            """
            SELECT
                segments_conversion_action,
                argMax({name}, segments_date) AS action_name,
                argMax({category}, segments_date),
                sum(toFloat(metrics_conversions)),
                sum(toFloat(metrics_all_conversions)) AS all_conversions
            FROM {table}
            WHERE toDate(segments_date) >= toDate({date_from}) AND toDate(segments_date) <= toDate({date_to})
            GROUP BY segments_conversion_action
            ORDER BY all_conversions DESC, action_name
            """,
            table,
            name=name,
            category=category,
        )
        recent = {row[0] for row in rows}
        # A saved action stays listed after it stops converting, so it can still be unchecked.
        idle = [action for action in self.saved_actions if action not in recent]
        if idle:
            rows += self._select(
                """
                SELECT segments_conversion_action, argMax({name}, segments_date) AS action_name, argMax({category}, segments_date), 0, 0
                FROM {table}
                WHERE has({idle}, segments_conversion_action)
                GROUP BY segments_conversion_action
                ORDER BY action_name
                """,
                table,
                name=name,
                category=category,
                idle=ast.Constant(value=idle),
            )
        account = self._account_label(source)
        return [
            MarketingAnalyticsConversionAction(
                action=row[0],
                name=row[1] or row[0],
                category=row[2] or None,
                account=account,
                campaignTable=source.campaignTable,
                primaryConversions=float(row[3] or 0),
                allConversions=float(row[4] or 0),
                recent=row[0] in recent,
            )
            for row in rows
            if row[0]
        ]
