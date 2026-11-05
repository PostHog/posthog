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
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import create_default_modifiers_for_team, execute_hogql_query

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_compare_to_date_range import QueryCompareToDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.ph_client import feature_enabled_or_false

from .access_control import MarketingAnalyticsAccessMixin
from .attribution_base import ConversionGoal
from .conversion_goal_conditions import conversion_goal_match_expr
from .marketing_analytics_config import MarketingAnalyticsConfig
from .search_conversion_query_runner import SearchConversionQueryRunner

MAX_POSTHOG_CONVERSION_GOALS = 5


class MarketingAnalyticsSearchQueryRunner(
    MarketingAnalyticsAccessMixin, AnalyticsQueryRunner[MarketingAnalyticsSearchQueryResponse]
):
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

    @cached_property
    def hogql_database(self) -> Database:
        return Database.create_for(
            team=self.team,
            user=self.user,
            modifiers=create_default_modifiers_for_team(self.team, self.modifiers),
            timings=self.timings,
        )

    @cached_property
    def hogql_context(self) -> HogQLContext:
        modifiers = create_default_modifiers_for_team(self.team, self.modifiers)
        return HogQLContext(
            team_id=self.team.pk,
            modifiers=modifiers,
            database=self.hogql_database,
        )

    def _placement_fields(self, source: MarketingAnalyticsSearchSource) -> dict[str, ast.Expr]:
        table = self.hogql_database.get_table(source.statsTable.split("."))
        fields = (
            ("top_rate", "top_impression_rate_percent"),
            ("absolute_top_rate", "absolute_top_impression_rate_percent"),
        )
        result: dict[str, ast.Expr] = {}
        for name, field in fields:
            value: ast.Expr = ast.Field(chain=["s", field]) if table.has_field(field) else ast.Constant(value=None)
            result[name] = (
                parse_expr("toFloatOrNull(replaceAll(toString({value}), '%', '')) / 100", placeholders={"value": value})
                if table.has_field(field)
                else value
            )
        return result

    @cached_property
    def unavailable_placement_tables(self) -> set[str]:
        if self.query.breakdown in ("page", "search_term"):
            return set()
        return {
            source.placementTable
            for source in self.query.sources
            if source.sourceType == "GoogleAds"
            and source.placementTable
            and (
                self.hogql_database.is_table_access_denied(source.placementTable)
                or not self.hogql_database.has_table(source.placementTable)
            )
        }

    def _google_keywords(self, keyword_table: str) -> ast.SelectQuery | ast.SelectSetQuery:
        return parse_select(
            """
            SELECT customer_id, campaign_id, ad_group_id, ad_group_criterion_criterion_id,
                any(ad_group_criterion_keyword_text) AS keyword,
                any(ad_group_criterion_keyword_match_type) AS match_type
            FROM {keywords}
            GROUP BY customer_id, campaign_id, ad_group_id, ad_group_criterion_criterion_id
            """,
            placeholders={"keywords": ast.Field(chain=[*keyword_table.split(".")])},
        )

    @cached_property
    def include_posthog_conversions(self) -> bool:
        # PostHog conversions match utm_term, which carries the targeted keyword, not the search term.
        return bool(
            self.query.includePostHogConversions
            and self.query.breakdown != "search_term"
            and not self.query.keyword
            and not self.query.page
            and feature_enabled_or_false(
                "marketing-analytics-search-conversions",
                str(self.team.uuid),
                groups={"organization": str(self.team.organization_id)},
                group_properties={"organization": {"id": str(self.team.organization_id)}},
            )
        )

    def get_cache_key_variant(self) -> str:
        variant = super().get_cache_key_variant()
        if self.query.includePostHogConversions:
            variant += f"_posthog_conversions_{int(self.include_posthog_conversions)}"
        if (
            self.include_posthog_conversions
            and MarketingAnalyticsConfig.from_team(self.team).live_session_resolution_enabled
        ):
            return f"{variant}_live_session_resolution"
        return variant

    def _page_expr(self, page: ast.Expr) -> ast.Expr:
        if self.include_posthog_conversions or self.query.normalizePageUrls:
            return ast.Call(name="cutQueryStringAndFragment", args=[page])
        return page

    def _google_search_terms_query(
        self, source: MarketingAnalyticsSearchSource, date_range: QueryDateRange, period: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        date_placeholders: dict[str, ast.Expr] = {
            "date_from": ast.Constant(value=date_range.date_from()),
            "date_to": ast.Constant(value=date_range.date_to()),
        }
        term_queries: list[ast.SelectQuery | ast.SelectSetQuery] = [
            parse_select(
                """
                SELECT customer_id, campaign_id, {term_column} AS term,
                    toFloat(metrics_clicks) AS clicks, toFloat(metrics_impressions) AS impressions,
                    toFloat(metrics_cost_micros) AS cost_micros, toFloat(metrics_conversions) AS conversions
                FROM {terms}
                WHERE toDate(segments_date) >= toDate({date_from}) AND toDate(segments_date) <= toDate({date_to})
                """,
                placeholders={
                    **date_placeholders,
                    "terms": ast.Field(chain=[*table.split(".")]),
                    "term_column": ast.Field(chain=[term_column]),
                },
            )
            for table, term_column in (
                (source.searchTermTable, "search_term_view_search_term"),
                (source.performanceMaxSearchTermTable, "campaign_search_term_view_search_term"),
            )
            if table
        ]
        if not term_queries:
            raise ValueError("Google Ads search terms require a synced search term table")
        # Search term tables do not carry the currency. It is set per account, so join on customer_id only:
        # a term whose campaign row is missing then still gets its account currency and stays in one row.
        return parse_select(
            """
            SELECT {period} AS period, nullIf(lower(trim(t.term)), '') AS keyword, NULL AS page,
                'GoogleAds' AS platform, NULL AS matchType, nullIf(c.currency, '') AS currency,
                sum(t.clicks) AS click_count, sum(t.impressions) AS impression_count,
                sum(t.cost_micros) / 1000000 AS total_cost, sum(t.conversions) AS conversion_count,
                0 AS position_total, NULL AS top_impressions, 0 AS top_eligible_impressions,
                NULL AS absolute_top_impressions, 0 AS absolute_top_eligible_impressions
            FROM {terms} AS t
            LEFT JOIN (
                SELECT customer_id, anyIf(upper(customer_currency_code), customer_currency_code != '') AS currency
                FROM {campaigns}
                GROUP BY customer_id
            ) AS c ON t.customer_id = c.customer_id
            GROUP BY keyword, currency
            """,
            placeholders={
                "period": ast.Constant(value=period),
                "terms": ast.SelectSetQuery.create_from_queries(term_queries, "UNION ALL"),
                "campaigns": ast.Field(chain=[*source.statsTable.split(".")]),
            },
        )

    def _source_query(
        self, source: MarketingAnalyticsSearchSource, date_range: QueryDateRange, period: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        if self.query.breakdown == "search_term" and source.sourceType == "GoogleAds":
            return self._google_search_terms_query(source, date_range, period)
        if self.query.breakdown == "search_term" and source.sourceType == "BingAds":
            raise ValueError("Search terms are supported by Google Ads and Google Search Console")
        placeholders: dict[str, ast.Expr] = {
            "period": ast.Constant(value=period),
            "stats": ast.Field(chain=[*source.statsTable.split(".")]),
            "date_from": ast.Constant(value=date_range.date_from()),
            "date_to": ast.Constant(value=date_range.date_to()),
        }
        if source.sourceType == "BingAds":
            placeholders.update(self._placement_fields(source))
        if source.sourceType == "GoogleSearchConsole":
            if (self.query.keyword is not None or self.query.page is not None) and not source.queryPageTable:
                raise ValueError("Search details require the query and page table")
            placeholders.update(
                {
                    "keyword_value": ast.Constant(value=None)
                    if self.query.breakdown == "page"
                    else parse_expr("nullIf(lower(trim(s.query)), '')"),
                    "page_value": self._page_expr(parse_expr("s.page"))
                    if self.query.breakdown == "page"
                    else ast.Constant(value=None),
                    "keyword_filter": parse_expr(
                        "lower(trim(s.query)) = {keyword}",
                        placeholders={"keyword": ast.Constant(value=self.query.keyword.strip().lower())},
                    )
                    if self.query.keyword is not None
                    else ast.Constant(value=True),
                    "page_filter": parse_expr(
                        "{page_value} = {page}",
                        placeholders={
                            "page_value": self._page_expr(parse_expr("s.page")),
                            "page": self._page_expr(ast.Constant(value=self.query.page)),
                        },
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
                    sum(toFloat(s.position) * toFloat(s.impressions)) AS position_total,
                    NULL AS top_impressions, 0 AS top_eligible_impressions,
                    NULL AS absolute_top_impressions, 0 AS absolute_top_eligible_impressions
                FROM {stats} AS s
                WHERE toDate(date) >= toDate({date_from}) AND toDate(date) <= toDate({date_to})
                    AND {keyword_filter} AND {page_filter}
                GROUP BY keyword, page
                """,
                placeholders=placeholders,
            )
        if self.query.breakdown == "page" and source.sourceType == "BingAds":
            placeholders["page_value"] = self._page_expr(parse_expr("destination_url"))
            return parse_select(
                """
                SELECT {period} AS period, NULL AS keyword, nullIf({page_value}, '') AS page,
                    'BingAds' AS platform, NULL AS matchType,
                    nullIf(upper(currency_code), '') AS currency,
                    sum(toFloat(clicks)) AS click_count, sum(toFloat(impressions)) AS impression_count,
                    sum(toFloat(spend)) AS total_cost,
                    sum(toFloat(conversions_qualified)) AS conversion_count, 0 AS position_total,
                    sum({top_rate} * toFloat(s.impressions)) AS top_impressions,
                    sumIf(toFloat(s.impressions), {top_rate} IS NOT NULL) AS top_eligible_impressions,
                    sum({absolute_top_rate} * toFloat(s.impressions)) AS absolute_top_impressions,
                    sumIf(toFloat(s.impressions), {absolute_top_rate} IS NOT NULL) AS absolute_top_eligible_impressions
                FROM {stats} AS s
                WHERE toDate(time_period) >= toDate({date_from}) AND toDate(time_period) <= toDate({date_to})
                    AND ad_distribution = 'Search'
                GROUP BY page, currency
                """,
                placeholders=placeholders,
            )
        if self.query.breakdown == "page":
            if source.sourceType != "GoogleAds":
                raise ValueError("Landing pages are supported by Google Ads and Google Search Console")
            placeholders["page_value"] = self._page_expr(parse_expr("landing_page_view_unexpanded_final_url"))
            return parse_select(
                """
                SELECT {period} AS period, NULL AS keyword,
                    nullIf({page_value}, '') AS page,
                    'GoogleAds' AS platform, NULL AS matchType,
                    nullIf(upper(customer_currency_code), '') AS currency,
                    sum(toFloat(metrics_clicks)) AS click_count,
                    sum(toFloat(metrics_impressions)) AS impression_count,
                    sum(toFloat(metrics_cost_micros)) / 1000000 AS total_cost,
                    sum(toFloat(metrics_conversions)) AS conversion_count, 0 AS position_total,
                    NULL AS top_impressions, 0 AS top_eligible_impressions,
                    NULL AS absolute_top_impressions, 0 AS absolute_top_eligible_impressions
                FROM {stats} AS s
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
            placeholders["keywords"] = self._google_keywords(source.keywordTable)
            return parse_select(
                """
                SELECT {period} AS period, nullIf(lower(trim(k.keyword)), '') AS keyword, NULL AS page, 'GoogleAds' AS platform,
                    nullIf(lower(k.match_type), '') AS matchType,
                    nullIf(upper(s.customer_currency_code), '') AS currency,
                    sum(toFloat(s.metrics_clicks)) AS click_count,
                    sum(toFloat(s.metrics_impressions)) AS impression_count,
                    sum(toFloat(s.metrics_cost_micros)) / 1000000 AS total_cost,
                    sum(toFloat(s.metrics_conversions)) AS conversion_count, 0 AS position_total,
                    NULL AS top_impressions, 0 AS top_eligible_impressions,
                    NULL AS absolute_top_impressions, 0 AS absolute_top_eligible_impressions
                FROM {stats} AS s
                LEFT JOIN {keywords} AS k ON s.customer_id = k.customer_id AND s.campaign_id = k.campaign_id
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
                sum(toFloat(spend)) AS total_cost, sum(toFloat(conversions)) AS conversion_count, 0 AS position_total,
                    sum({top_rate} * toFloat(s.impressions)) AS top_impressions,
                    sumIf(toFloat(s.impressions), {top_rate} IS NOT NULL) AS top_eligible_impressions,
                    sum({absolute_top_rate} * toFloat(s.impressions)) AS absolute_top_impressions,
                    sumIf(toFloat(s.impressions), {absolute_top_rate} IS NOT NULL) AS absolute_top_eligible_impressions
            FROM {stats} AS s
            WHERE toDate(time_period) >= toDate({date_from}) AND toDate(time_period) <= toDate({date_to})
            GROUP BY keyword, matchType, currency
            """,
            placeholders=placeholders,
        )

    def _google_placement_query(
        self, source: MarketingAnalyticsSearchSource, date_range: QueryDateRange, period: int
    ) -> ast.SelectQuery | ast.SelectSetQuery:
        if not source.placementTable or not source.keywordTable:
            raise ValueError("Google Ads placement requires synced keyword and keyword placement tables")
        # Name keywords from the keyword table, as traffic does, so a criterion it lacks does not split into two rows.
        return parse_select(
            """
            SELECT {period} AS period,
                nullIf(lower(trim(k.keyword)), '') AS keyword,
                NULL AS page, 'GoogleAds' AS platform,
                nullIf(lower(k.match_type), '') AS matchType,
                nullIf(upper(p.customer_currency_code), '') AS currency,
                0 AS click_count, 0 AS impression_count, 0 AS total_cost,
                0 AS conversion_count, 0 AS position_total,
                sum(toFloat(p.metrics_top_impression_percentage) * toFloat(p.metrics_impressions)) AS top_impressions,
                sumIf(toFloat(p.metrics_impressions), p.metrics_top_impression_percentage IS NOT NULL) AS top_eligible_impressions,
                sum(toFloat(p.metrics_absolute_top_impression_percentage) * toFloat(p.metrics_impressions)) AS absolute_top_impressions,
                sumIf(toFloat(p.metrics_impressions), p.metrics_absolute_top_impression_percentage IS NOT NULL) AS absolute_top_eligible_impressions
            FROM {placement} AS p
            LEFT JOIN {keywords} AS k ON p.customer_id = k.customer_id AND p.campaign_id = k.campaign_id
                AND p.ad_group_id = k.ad_group_id
                AND p.ad_group_criterion_criterion_id = k.ad_group_criterion_criterion_id
            WHERE toDate(p.segments_date) >= toDate({date_from})
                AND toDate(p.segments_date) <= toDate({date_to})
                AND p.segments_ad_network_type = 'SEARCH'
            GROUP BY keyword, matchType, currency
            """,
            placeholders={
                "period": ast.Constant(value=period),
                "placement": ast.Field(chain=[*source.placementTable.split(".")]),
                "keywords": self._google_keywords(source.keywordTable),
                "date_from": ast.Constant(value=date_range.date_from()),
                "date_to": ast.Constant(value=date_range.date_to()),
            },
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        source_queries = [self._source_query(source, self.query_date_range, 0) for source in self.query.sources]
        if self.comparison_date_range:
            source_queries.extend(
                self._source_query(source, self.comparison_date_range, 1) for source in self.query.sources
            )
        if self.query.breakdown not in ("page", "search_term"):
            for source in self.query.sources:
                if (
                    source.sourceType == "GoogleAds"
                    and source.placementTable
                    and source.placementTable not in self.unavailable_placement_tables
                ):
                    source_queries.append(self._google_placement_query(source, self.query_date_range, 0))
                    if self.comparison_date_range:
                        source_queries.append(self._google_placement_query(source, self.comparison_date_range, 1))
        sources = ast.SelectSetQuery.create_from_queries(source_queries, "UNION ALL")
        return parse_select(
            """
            SELECT keyword, page, platform, matchType, currency,
                {attribution_row_count} AS attribution_row_count,
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
                if(platform = 'GoogleSearchConsole', sumIf(position_total, period = 1) / nullIf(sumIf(impression_count, period = 1), 0), NULL) AS previous_position,
                sumIf(top_impressions, period = 0) / nullIf(sumIf(top_eligible_impressions, period = 0), 0) AS topImpressionRate,
                sumIf(absolute_top_impressions, period = 0) / nullIf(sumIf(absolute_top_eligible_impressions, period = 0), 0) AS absoluteTopImpressionRate,
                sumIf(top_impressions, period = 1) / nullIf(sumIf(top_eligible_impressions, period = 1), 0) AS previous_topImpressionRate,
                sumIf(absolute_top_impressions, period = 1) / nullIf(sumIf(absolute_top_eligible_impressions, period = 1), 0) AS previous_absoluteTopImpressionRate
            FROM {sources}
            WHERE positionCaseInsensitive(coalesce(keyword, page, ''), {search}) > 0
            GROUP BY keyword, page, platform, matchType, currency
            ORDER BY clicks DESC, impressions DESC, previous_clicks DESC, platform, keyword, page, matchType, currency
            LIMIT 100
            """,
            placeholders={
                "sources": sources,
                "search": ast.Constant(value=(self.query.search or "").strip()),
                "attribution_row_count": parse_expr("count() OVER (PARTITION BY keyword, page, platform)")
                if self.include_posthog_conversions
                else ast.Constant(value=1),
            },
        )

    def _conversion_key(self, row: MarketingAnalyticsSearchRow) -> str | None:
        value = row.page if self.query.breakdown == "page" else row.keyword
        if not value or (self.query.breakdown != "page" and row.platform == "GoogleSearchConsole"):
            return None
        return SearchConversionQueryRunner.row_key(value, row.platform)

    def _add_posthog_conversions(
        self, response: MarketingAnalyticsSearchQueryResponse, ambiguous_keys: set[str]
    ) -> None:
        keys = list(
            dict.fromkeys(
                key for row in response.results if (key := self._conversion_key(row)) and key not in ambiguous_keys
            )
        )
        breakdown = (
            MarketingAnalyticsAttributionBreakdown.LANDING_PAGE
            if self.query.breakdown == "page"
            else MarketingAnalyticsAttributionBreakdown.TERM
        )
        goal_runner = SearchConversionQueryRunner(
            query=MarketingAnalyticsAttributionQuery(properties=[], conversionGoalId="", breakdownBy=breakdown),
            team=self.team,
            user=self.user,
            modifiers=self.modifiers,
            timings=self.timings,
            limit_context=self.limit_context,
        )
        goal_runner.__dict__["_shared_hogql_database"] = self.hogql_database
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
                "Search performance supports event and action goals. Data warehouse goals are not included."
            )
        if ambiguous_keys:
            warnings.append(
                "PostHog conversions are unavailable for pages with spend in multiple currencies because conversion credit cannot be split by ad account."
                if self.query.breakdown == "page"
                else "PostHog conversions are unavailable for keywords with multiple match types or currencies because conversion credit cannot be split between those rows."
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
                        breakdownBy=breakdown,
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
                periods.append(runner.calculate_conversions())
            for row in response.results:
                key = self._conversion_key(row)
                current = periods[0].get(key, 0.0) if key and key not in ambiguous_keys else None
                previous = (
                    periods[1].get(key, 0.0) if key and current is not None and self.comparison_date_range else None
                )
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
            context=self.hogql_context,
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
            attribution_row_count = values.pop("attribution_row_count")
            previous = {
                metric: values.pop(f"previous_{metric}") for metric in MarketingAnalyticsSearchMetrics.model_fields
            }
            rows.append(
                MarketingAnalyticsSearchRow(
                    **values,
                    previous=MarketingAnalyticsSearchMetrics(**previous) if self.comparison_date_range else None,
                )
            )
            if attribution_row_count > 1 and (key := self._conversion_key(rows[-1])):
                ambiguous_keys.add(key)
        response = MarketingAnalyticsSearchQueryResponse(
            results=rows, placementUnavailable=bool(self.unavailable_placement_tables)
        )
        if self.include_posthog_conversions:
            self._add_posthog_conversions(response, ambiguous_keys)
        return response
