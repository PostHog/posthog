from datetime import datetime
from functools import cached_property

from posthog.schema import (
    CachedMarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchMetrics,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchQueryResponse,
    MarketingAnalyticsSearchRow,
    MarketingAnalyticsSearchSource,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange


class MarketingAnalyticsSearchQueryRunner(AnalyticsQueryRunner[MarketingAnalyticsSearchQueryResponse]):
    query: MarketingAnalyticsSearchQuery
    response: MarketingAnalyticsSearchQueryResponse
    cached_response: CachedMarketingAnalyticsSearchQueryResponse

    @cached_property
    def now(self) -> datetime:
        return datetime.now()

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(date_range=self.query.dateRange, team=self.team, interval=None, now=self.now)

    @cached_property
    def comparison_date_range(self) -> QueryDateRange | None:
        if not self.query.compareFilter or not self.query.compareFilter.compare:
            return None
        if self.query.compareFilter.compare_to:
            return QueryCompareToDateRange(
                date_range=self.query.dateRange,
                team=self.team,
                interval=None,
                now=self.now,
                compare_to=self.query.compareFilter.compare_to,
            )
        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=self.now,
        )

    def _source_query(
        self, source: MarketingAnalyticsSearchSource, date_range: QueryDateRange, period: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        placeholders: dict[str, ast.Expr] = {
            "period": ast.Constant(value=period),
            "stats": ast.Field(chain=[*source.statsTable.split(".")]),
            "date_from": ast.Constant(value=date_range.date_from()),
            "date_to": ast.Constant(value=date_range.date_to()),
        }
        if source.sourceType == "GoogleSearchConsole":
            if (self.query.keyword is not None or self.query.page is not None) and not source.queryPageTable:
                raise ValueError("Search details require the query and page table")
            placeholders.update(
                {
                    "keyword_value": ast.Constant(value=None)
                    if self.query.breakdown == "page"
                    else parse_expr("nullIf(lower(trim(s.query)), '')"),
                    "page_value": ast.Field(chain=["s", "page"])
                    if self.query.breakdown == "page"
                    else ast.Constant(value=None),
                    "keyword_filter": parse_expr(
                        "lower(trim(s.query)) = {keyword}",
                        placeholders={"keyword": ast.Constant(value=self.query.keyword.strip().lower())},
                    )
                    if self.query.keyword is not None
                    else ast.Constant(value=True),
                    "page_filter": parse_expr(
                        "s.page = {page}", placeholders={"page": ast.Constant(value=self.query.page)}
                    )
                    if self.query.page is not None
                    else ast.Constant(value=True),
                }
            )
            return parse_select(
                """
                SELECT {period} AS period, {keyword_value} AS keyword, {page_value} AS page,
                    'GoogleSearchConsole' AS platform, NULL AS matchType, NULL AS currency,
                    sum(toFloat(clicks)) AS click_count, sum(toFloat(impressions)) AS impression_count,
                    0 AS total_cost, 0 AS conversion_count,
                    sum(toFloat(s.position) * toFloat(s.impressions)) AS position_total
                FROM {stats} AS s
                WHERE toDate(date) >= toDate({date_from}) AND toDate(date) <= toDate({date_to})
                    AND {keyword_filter} AND {page_filter}
                GROUP BY keyword, page
                """,
                placeholders=placeholders,
            )
        if self.query.breakdown == "page":
            if source.sourceType != "GoogleAds":
                raise ValueError("Landing pages are supported by Google Ads and Google Search Console")
            return parse_select(
                """
                SELECT {period} AS period, NULL AS keyword,
                    nullIf(landing_page_view_unexpanded_final_url, '') AS page,
                    'GoogleAds' AS platform, NULL AS matchType,
                    nullIf(upper(customer_currency_code), '') AS currency,
                    sum(toFloat(metrics_clicks)) AS click_count,
                    sum(toFloat(metrics_impressions)) AS impression_count,
                    sum(toFloat(metrics_cost_micros)) / 1000000 AS total_cost,
                    sum(toFloat(metrics_conversions)) AS conversion_count, 0 AS position_total
                FROM {stats}
                WHERE toDate(segments_date) >= toDate({date_from})
                    AND toDate(segments_date) <= toDate({date_to})
                    AND segments_ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
                GROUP BY page, currency
                """,
                placeholders=placeholders,
            )
        if source.sourceType == "GoogleAds":
            if not source.keywordTable:
                raise ValueError("Google Ads requires a synced keyword table")
            placeholders["keywords"] = ast.Field(chain=[*source.keywordTable.split(".")])
            return parse_select(
                """
                SELECT {period} AS period, nullIf(lower(trim(k.keyword)), '') AS keyword, NULL AS page, 'GoogleAds' AS platform,
                    nullIf(lower(k.match_type), '') AS matchType,
                    nullIf(upper(s.customer_currency_code), '') AS currency,
                    sum(toFloat(s.metrics_clicks)) AS click_count,
                    sum(toFloat(s.metrics_impressions)) AS impression_count,
                    sum(toFloat(s.metrics_cost_micros)) / 1000000 AS total_cost,
                    sum(toFloat(s.metrics_conversions)) AS conversion_count, 0 AS position_total
                FROM {stats} AS s
                LEFT JOIN (
                    SELECT customer_id, campaign_id, ad_group_id, ad_group_criterion_criterion_id,
                        any(ad_group_criterion_keyword_text) AS keyword,
                        any(ad_group_criterion_keyword_match_type) AS match_type
                    FROM {keywords}
                    GROUP BY customer_id, campaign_id, ad_group_id, ad_group_criterion_criterion_id
                ) AS k ON s.customer_id = k.customer_id AND s.campaign_id = k.campaign_id
                    AND s.ad_group_id = k.ad_group_id
                    AND s.ad_group_criterion_criterion_id = k.ad_group_criterion_criterion_id
                WHERE toDate(s.segments_date) >= toDate({date_from})
                    AND toDate(s.segments_date) <= toDate({date_to})
                    AND s.segments_ad_network_type IN ('SEARCH', 'SEARCH_PARTNERS')
                GROUP BY keyword, matchType, currency
                """,
                placeholders=placeholders,
            )
        return parse_select(
            """
            SELECT {period} AS period, nullIf(lower(trim(keyword)), '') AS keyword, NULL AS page, 'BingAds' AS platform,
                nullIf(lower(bid_match_type), '') AS matchType, nullIf(upper(currency_code), '') AS currency,
                sum(toFloat(clicks)) AS click_count, sum(toFloat(impressions)) AS impression_count,
                sum(toFloat(spend)) AS total_cost, sum(toFloat(conversions)) AS conversion_count, 0 AS position_total
            FROM {stats}
            WHERE toDate(time_period) >= toDate({date_from}) AND toDate(time_period) <= toDate({date_to})
            GROUP BY keyword, matchType, currency
            """,
            placeholders=placeholders,
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        source_queries = [self._source_query(source, self.query_date_range, 0) for source in self.query.sources]
        if self.comparison_date_range:
            source_queries.extend(
                self._source_query(source, self.comparison_date_range, 1) for source in self.query.sources
            )
        sources = ast.SelectSetQuery.create_from_queries(source_queries, "UNION ALL")
        return parse_select(
            """
            SELECT keyword, page, platform, matchType, currency,
                coalesce(sumIf(click_count, period = 0), 0) AS clicks, coalesce(sumIf(impression_count, period = 0), 0) AS impressions,
                if(platform = 'GoogleSearchConsole', NULL, coalesce(sumIf(total_cost, period = 0), 0)) AS cost,
                if(platform = 'GoogleSearchConsole', NULL, coalesce(sumIf(conversion_count, period = 0), 0)) AS conversions,
                sumIf(click_count, period = 0) / nullIf(sumIf(impression_count, period = 0), 0) AS ctr,
                if(platform = 'GoogleSearchConsole', NULL, sumIf(total_cost, period = 0) / nullIf(sumIf(click_count, period = 0), 0)) AS cpc,
                sumIf(total_cost, period = 0) / nullIf(sumIf(conversion_count, period = 0), 0) AS cpa,
                coalesce(sumIf(click_count, period = 1), 0) AS previous_clicks,
                coalesce(sumIf(impression_count, period = 1), 0) AS previous_impressions,
                if(platform = 'GoogleSearchConsole', NULL, coalesce(sumIf(total_cost, period = 1), 0)) AS previous_cost,
                if(platform = 'GoogleSearchConsole', NULL, coalesce(sumIf(conversion_count, period = 1), 0)) AS previous_conversions,
                sumIf(click_count, period = 1) / nullIf(sumIf(impression_count, period = 1), 0) AS previous_ctr,
                if(platform = 'GoogleSearchConsole', NULL, sumIf(total_cost, period = 1) / nullIf(sumIf(click_count, period = 1), 0)) AS previous_cpc,
                sumIf(total_cost, period = 1) / nullIf(sumIf(conversion_count, period = 1), 0) AS previous_cpa,
                if(platform = 'GoogleSearchConsole', sumIf(position_total, period = 0) / nullIf(sumIf(impression_count, period = 0), 0), NULL) AS position,
                if(platform = 'GoogleSearchConsole', sumIf(position_total, period = 1) / nullIf(sumIf(impression_count, period = 1), 0), NULL) AS previous_position
            FROM {sources}
            WHERE positionCaseInsensitive(coalesce(keyword, page, ''), {search}) > 0
            GROUP BY keyword, page, platform, matchType, currency
            ORDER BY clicks DESC, impressions DESC, previous_clicks DESC, platform, keyword, page, matchType, currency
            LIMIT 100
            """,
            placeholders={"sources": sources, "search": ast.Constant(value=(self.query.search or "").strip())},
        )

    def _calculate(self) -> MarketingAnalyticsSearchQueryResponse:
        if not self.query.sources:
            return MarketingAnalyticsSearchQueryResponse(results=[])
        result = execute_hogql_query(
            query_type="marketing_analytics_search_query",
            query=self.to_query(),
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        rows = []
        for row in result.results:
            values = dict(zip(result.columns or [], row))
            previous = {
                metric: values.pop(f"previous_{metric}") for metric in MarketingAnalyticsSearchMetrics.model_fields
            }
            rows.append(
                MarketingAnalyticsSearchRow(
                    **values,
                    previous=MarketingAnalyticsSearchMetrics(**previous) if self.comparison_date_range else None,
                )
            )
        return MarketingAnalyticsSearchQueryResponse(results=rows)
