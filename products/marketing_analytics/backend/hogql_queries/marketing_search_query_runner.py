from datetime import datetime
from functools import cached_property

from posthog.schema import (
    CachedMarketingAnalyticsSearchQueryResponse,
    DateRange,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsSearchConversion,
    MarketingAnalyticsSearchConversionGoal,
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

from .attribution_base import ConversionGoal
from .conversion_goal_conditions import conversion_goal_match_expr
from .marketing_analytics_config import MarketingAnalyticsConfig
from .search_conversion_query_runner import SearchConversionQueryRunner

MAX_POSTHOG_CONVERSION_GOALS = 5


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

    @property
    def include_posthog_conversions(self) -> bool:
        return bool(self.query.includePostHogConversions and self.query.breakdown == "page" and not self.query.keyword)

    def get_cache_key_variant(self) -> str:
        variant = super().get_cache_key_variant()
        if (
            self.include_posthog_conversions
            and MarketingAnalyticsConfig.from_team(self.team).live_session_resolution_enabled
        ):
            return f"{variant}_live_session_resolution"
        return variant

    def _page_expr(self, field: str) -> ast.Expr:
        page = parse_expr(field)
        return ast.Call(name="cutQueryStringAndFragment", args=[page]) if self.include_posthog_conversions else page

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
                    "page_value": self._page_expr("s.page")
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
        if self.query.breakdown == "page" and source.sourceType == "BingAds":
            placeholders["page_value"] = self._page_expr("destination_url")
            return parse_select(
                """
                SELECT {period} AS period, NULL AS keyword, nullIf({page_value}, '') AS page,
                    'BingAds' AS platform, NULL AS matchType,
                    nullIf(upper(currency_code), '') AS currency,
                    sum(toFloat(clicks)) AS click_count, sum(toFloat(impressions)) AS impression_count,
                    sum(toFloat(spend)) AS total_cost,
                    sum(toFloat(conversions_qualified)) AS conversion_count, 0 AS position_total
                FROM {stats}
                WHERE toDate(time_period) >= toDate({date_from}) AND toDate(time_period) <= toDate({date_to})
                    AND ad_distribution = 'Search'
                GROUP BY page, currency
                """,
                placeholders=placeholders,
            )
        if self.query.breakdown == "page":
            if source.sourceType != "GoogleAds":
                raise ValueError("Landing pages are supported by Google Ads and Google Search Console")
            placeholders["page_value"] = self._page_expr("landing_page_view_unexpanded_final_url")
            return parse_select(
                """
                SELECT {period} AS period, NULL AS keyword,
                    nullIf({page_value}, '') AS page,
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
                {currency_count} AS currency_count,
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
            placeholders={
                "sources": sources,
                "search": ast.Constant(value=(self.query.search or "").strip()),
                "currency_count": parse_expr("uniqExact(ifNull(currency, '')) OVER (PARTITION BY page, platform)")
                if self.include_posthog_conversions
                else ast.Constant(value=1),
            },
        )

    def _add_posthog_conversions(
        self, response: MarketingAnalyticsSearchQueryResponse, ambiguous_keys: set[str]
    ) -> None:
        keys = [SearchConversionQueryRunner.row_key(row.page, row.platform) for row in response.results if row.page]
        goal_runner = SearchConversionQueryRunner(
            query=MarketingAnalyticsAttributionQuery(
                properties=[], conversionGoalId="", breakdownBy=MarketingAnalyticsAttributionBreakdown.LANDING_PAGE
            ),
            team=self.team,
            user=self.user,
            modifiers=self.modifiers,
            timings=self.timings,
            limit_context=self.limit_context,
        )
        goals = goal_runner._get_team_conversion_goals()
        event_goals: list[ConversionGoal] = [goal for goal in goals if goal.kind != "DataWarehouseNode"]
        filtered_goals, skipped_goals = goal_runner._filter_invalid_conversion_goals(event_goals)
        warnings = [goal.message for goal in skipped_goals]
        # The attribution runner raises on a goal whose action was deleted, so skip it before the goal cap.
        valid_goals: list[ConversionGoal] = []
        for goal in filtered_goals:
            if conversion_goal_match_expr(goal, self.team) is None:
                warnings.append(
                    f"Conversion goal '{goal.conversion_goal_name}' skipped: its action no longer exists. "
                    "Update the goal in Marketing analytics settings."
                )
            else:
                valid_goals.append(goal)
        if len(valid_goals) > MAX_POSTHOG_CONVERSION_GOALS:
            warnings.append(
                f"Search performance shows the first {MAX_POSTHOG_CONVERSION_GOALS} supported PostHog goals. "
                "Use the attribution report to view other goals."
            )
            valid_goals = valid_goals[:MAX_POSTHOG_CONVERSION_GOALS]
        response.posthogConversionGoals = [
            MarketingAnalyticsSearchConversionGoal(id=goal.conversion_goal_id, name=goal.conversion_goal_name)
            for goal in valid_goals
        ]
        response.posthogAttributionMode = goal_runner.config.attribution_mode
        if len(event_goals) != len(goals):
            warnings.append(
                "Landing page attribution supports event and action goals. Data warehouse goals are not included."
            )
        if ambiguous_keys:
            warnings.append(
                "PostHog conversions are unavailable for pages with spend in multiple currencies because conversion credit cannot be split by ad account."
            )
        response.posthogConversionsWarning = " ".join(warnings) or None
        for row in response.results:
            row.posthogConversions = []
        if not keys:
            return
        for goal in valid_goals:
            periods: list[dict[str, float]] = []
            for date_range in [self.query_date_range, self.comparison_date_range]:
                if date_range is None:
                    periods.append({})
                    continue
                runner = SearchConversionQueryRunner(
                    query=MarketingAnalyticsAttributionQuery(
                        properties=[],
                        conversionGoalId=goal.conversion_goal_id,
                        breakdownBy=MarketingAnalyticsAttributionBreakdown.LANDING_PAGE,
                        dateRange=DateRange(
                            date_from=date_range.date_from().isoformat(),
                            date_to=date_range.date_to().isoformat(),
                            explicitDate=True,
                        ),
                        limit=len(keys),
                    ),
                    team=self.team,
                    user=self.user,
                    modifiers=self.modifiers,
                    timings=self.timings,
                    limit_context=self.limit_context,
                )
                runner.search_keys = keys
                # Share one HogQL database across goals and periods, so the request pays Database.create_for once.
                runner.__dict__["_shared_hogql_database"] = goal_runner._shared_hogql_database
                periods.append(
                    {
                        row.breakdownValue: next(
                            cell.conversions for cell in row.models if cell.model == response.posthogAttributionMode
                        )
                        for row in runner.calculate().results
                    }
                )
            for row in response.results:
                key = SearchConversionQueryRunner.row_key(row.page, row.platform)
                current = periods[0].get(key, 0.0) if row.page and key not in ambiguous_keys else None
                previous = periods[1].get(key, 0.0) if current is not None and self.comparison_date_range else None
                assert row.posthogConversions is not None
                row.posthogConversions.append(
                    MarketingAnalyticsSearchConversion(
                        id=goal.conversion_goal_id,
                        name=goal.conversion_goal_name,
                        conversions=current,
                        costPerConversion=row.cost / current if row.cost is not None and current else None,
                        previousConversions=previous,
                        previousCostPerConversion=row.previous.cost / previous
                        if row.previous and row.previous.cost is not None and previous
                        else None,
                    )
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
        rows: list[MarketingAnalyticsSearchRow] = []
        ambiguous_keys: set[str] = set()
        for row in result.results:
            values = dict(zip(result.columns or [], row))
            if values.pop("currency_count") > 1:
                ambiguous_keys.add(SearchConversionQueryRunner.row_key(values.get("page"), values["platform"]))
            previous = {
                metric: values.pop(f"previous_{metric}") for metric in MarketingAnalyticsSearchMetrics.model_fields
            }
            rows.append(
                MarketingAnalyticsSearchRow(
                    **values,
                    previous=MarketingAnalyticsSearchMetrics(**previous) if self.comparison_date_range else None,
                )
            )
        response = MarketingAnalyticsSearchQueryResponse(results=rows)
        if self.include_posthog_conversions:
            self._add_posthog_conversions(response, ambiguous_keys)
        return response
