from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.schema import (
    AttributionMode,
    BaseMathType,
    Breakdown1,
    CompareFilter,
    ConversionGoalFilter1,
    DateRange,
    EventPropertyFilter,
    HogQLQueryResponse,
    MarketingAnalyticsSearchMetrics,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchSource,
    PropertyOperator,
    SessionTableVersion,
)

from posthog.hogql.database.database import Database

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.utils import uuid7
from posthog.test.persons import create_person

from products.access_control.backend.models.access_control import AccessControl
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

from .marketing_search_query_runner import MarketingAnalyticsSearchQueryRunner


class TestMarketingAnalyticsSearchQueryRunner(ClickhouseTestMixin, BaseTest):
    def _table(self, name: str, columns: dict[str, str], csv: str) -> str:
        with TemporaryDirectory() as directory:
            path = Path(directory) / f"{name}.csv"
            path.write_text(csv)
            table, _, _, _, cleanup = create_data_warehouse_table_from_csv(
                path, name, columns, f"test_storage_bucket-posthog.marketing_analytics.{name}", self.team
            )
        self.addCleanup(cleanup)
        return table.name

    def test_combines_platforms_without_multiplying_metrics_or_mixing_currencies(self) -> None:
        keywords = self._table(
            "search_keywords",
            {
                "customer_id": "Int64",
                "campaign_id": "Int64",
                "ad_group_id": "Int64",
                "ad_group_criterion_criterion_id": "Int64",
                "ad_group_criterion_keyword_text": "String",
                "ad_group_criterion_keyword_match_type": "String",
            },
            "customer_id,campaign_id,ad_group_id,ad_group_criterion_criterion_id,ad_group_criterion_keyword_text,ad_group_criterion_keyword_match_type\n"
            "1,10,100,7,Hedgehog,EXACT\n1,10,100,7,Hedgehog,EXACT\n"
            "2,20,200,7,Other keyword,PHRASE\n",
        )
        google_stats = self._table(
            "search_google_stats",
            {
                "customer_id": "Int64",
                "campaign_id": "Int64",
                "ad_group_id": "Int64",
                "ad_group_criterion_criterion_id": "Int64",
                "customer_currency_code": "String",
                "metrics_clicks": "Float64",
                "metrics_impressions": "Float64",
                "metrics_cost_micros": "Float64",
                "metrics_conversions": "Float64",
                "segments_date": "Date",
                "segments_ad_network_type": "String",
            },
            "customer_id,campaign_id,ad_group_id,ad_group_criterion_criterion_id,customer_currency_code,metrics_clicks,metrics_impressions,metrics_cost_micros,metrics_conversions,segments_date,segments_ad_network_type\n"
            "1,10,100,7,USD,10,100,20000000,2,2023-01-10,SEARCH\n"
            "1,10,100,7,USD,30,900,40000000,0.5,2023-01-11,SEARCH_PARTNERS\n"
            "1,10,100,7,EUR,5,100,10000000,1,2023-01-10,SEARCH\n"
            "1,10,100,7,USD,900,9000,90000000,9,2023-01-10,CONTENT\n"
            "1,10,100,7,USD,20,200,30000000,1.25,2022-12-15,SEARCH\n"
            "1,10,100,7,USD,8,80,16000000,2,2022-01-10,SEARCH\n"
            "2,20,200,7,USD,3,100,6000000,1,2023-01-10,SEARCH\n",
        )
        bing_stats = self._table(
            "search_bing_stats",
            {
                "keyword": "String",
                "bid_match_type": "String",
                "currency_code": "String",
                "clicks": "Float64",
                "impressions": "Float64",
                "spend": "Float64",
                "conversions": "Float64",
                "time_period": "Date",
            },
            "keyword,bid_match_type,currency_code,clicks,impressions,spend,conversions,time_period\n"
            "Hedgehog,Exact,USD,4,80,8,1,2023-01-10\n"
            "Hedgehog,Phrase,USD,1,20,2,0,2023-01-10\n"
            "Zero,Exact,USD,0,0,0,0,2023-01-10\n"
            "Previous only,Exact,USD,5,100,10,0.5,2022-12-15\n",
        )
        query = MarketingAnalyticsSearchQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            sources=[
                MarketingAnalyticsSearchSource(sourceType="GoogleAds", statsTable=google_stats, keywordTable=keywords),
                MarketingAnalyticsSearchSource(sourceType="BingAds", statsTable=bing_stats),
            ],
        )
        rows = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert len(rows) == 6
        google = next(
            row for row in rows if row.platform == "GoogleAds" and row.currency == "USD" and row.keyword == "hedgehog"
        )
        assert google.model_dump() == {
            "keyword": "hedgehog",
            "page": None,
            "position": None,
            "platform": "GoogleAds",
            "matchType": "exact",
            "currency": "USD",
            "clicks": 40,
            "impressions": 1000,
            "cost": 60,
            "conversions": 2.5,
            "ctr": 0.04,
            "cpc": 1.5,
            "cpa": 24,
            "previous": None,
            "posthogConversions": None,
        }
        zero = next(row for row in rows if row.keyword == "zero")
        assert zero.ctr is None and zero.cpc is None and zero.cpa is None
        assert next(row for row in rows if row.keyword == "other keyword").clicks == 3
        query.search = "HEDGE"
        filtered = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert len(filtered) == 4
        assert all(row.keyword == "hedgehog" for row in filtered)

        query.search = None
        query.compareFilter = CompareFilter(compare=True)
        compared = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert len(compared) == 7
        google_compared = next(
            row
            for row in compared
            if row.platform == "GoogleAds" and row.currency == "USD" and row.keyword == "hedgehog"
        )
        assert google_compared.clicks == 40
        assert google_compared.previous is not None
        assert google_compared.previous.model_dump() == {
            "clicks": 20,
            "impressions": 200,
            "cost": 30,
            "conversions": 1.25,
            "ctr": 0.1,
            "cpc": 1.5,
            "cpa": 24,
            "position": None,
        }
        previous_only = next(row for row in compared if row.keyword == "previous only")
        assert previous_only.clicks == 0
        assert previous_only.ctr is None and previous_only.cpc is None and previous_only.cpa is None
        assert previous_only.previous is not None and previous_only.previous.clicks == 5
        new_keyword = next(row for row in compared if row.keyword == "other keyword")
        assert new_keyword.previous is not None and new_keyword.previous.clicks == 0
        assert new_keyword.previous.ctr is None

        query.compareFilter = CompareFilter(compare=True, compare_to="-1y")
        year_compared = (
            MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        )
        previous_year = next(
            row
            for row in year_compared
            if row.platform == "GoogleAds" and row.currency == "USD" and row.keyword == "hedgehog"
        )
        assert previous_year.clicks == 40
        assert previous_year.previous is not None and previous_year.previous.clicks == 8
        assert not any(row.keyword == "previous only" for row in year_compared)

    @parameterized.expand([("GoogleAds",), ("BingAds",)])
    def test_landing_pages_exclude_non_search_traffic_and_keep_currencies(self, platform: str) -> None:
        if platform == "GoogleAds":
            table = self._table(
                "paid_landing_pages",
                {
                    "segments_date": "Date",
                    "landing_page_view_unexpanded_final_url": "String",
                    "segments_ad_network_type": "String",
                    "customer_currency_code": "String",
                    "metrics_clicks": "Float64",
                    "metrics_impressions": "Float64",
                    "metrics_cost_micros": "Float64",
                    "metrics_conversions": "Float64",
                },
                "segments_date,landing_page_view_unexpanded_final_url,segments_ad_network_type,customer_currency_code,metrics_clicks,metrics_impressions,metrics_cost_micros,metrics_conversions\n"
                "2023-01-10,https://example.com/a,SEARCH,USD,10,100,20000000,2\n"
                "2023-01-11,https://example.com/a,SEARCH_PARTNERS,USD,5,50,10000000,0.5\n"
                "2023-01-10,https://example.com/a,SEARCH,EUR,3,30,6000000,1\n"
                "2023-01-10,https://example.com/a,CONTENT,USD,900,9000,90000000,90\n",
            )
        else:
            table = self._table(
                "bing_landing_pages",
                {
                    "time_period": "Date",
                    "destination_url": "String",
                    "ad_distribution": "String",
                    "currency_code": "String",
                    "clicks": "Float64",
                    "impressions": "Float64",
                    "spend": "Float64",
                    "conversions_qualified": "Float64",
                },
                "time_period,destination_url,ad_distribution,currency_code,clicks,impressions,spend,conversions_qualified\n"
                "2023-01-10,https://example.com/a,Search,USD,10,100,20,2\n"
                "2023-01-11,https://example.com/a,Search,USD,5,50,10,0.5\n"
                "2023-01-10,https://example.com/a,Search,EUR,3,30,6,1\n"
                "2023-01-10,https://example.com/a,Audience,USD,900,9000,90,90\n"
                "2022-01-10,https://example.com/a,Search,USD,900,9000,90,90\n",
            )
        query = MarketingAnalyticsSearchQuery(
            breakdown="page",
            sources=[MarketingAnalyticsSearchSource(sourceType=platform, statsTable=table)],
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
        )
        rows = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert len(rows) == 2
        usd = next(row for row in rows if row.currency == "USD")
        assert usd.page == "https://example.com/a" and usd.keyword is None
        assert usd.clicks == 15 and usd.impressions == 150
        assert usd.cost == 30 and usd.conversions == 2.5 and usd.position is None

    def test_organic_positions_are_weighted_and_details_keep_query_page_filters(self) -> None:
        table = self._table(
            "organic_query_pages",
            {
                "date": "Date",
                "query": "String",
                "page": "String",
                "clicks": "Float64",
                "impressions": "Float64",
                "position": "Float64",
            },
            "date,query,page,clicks,impressions,position\n"
            "2023-01-10,Analytics,https://example.com/a,10,100,1\n"
            "2023-01-10,Analytics,https://example.com/b,90,900,9\n"
            "2023-01-10,Other,https://example.com/a,5,50,2\n"
            "2022-12-15,Analytics,https://example.com/a,8,200,4\n",
        )
        query = MarketingAnalyticsSearchQuery(
            sources=[
                MarketingAnalyticsSearchSource(sourceType="GoogleSearchConsole", statsTable=table, queryPageTable=True)
            ],
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            compareFilter=CompareFilter(compare=True),
        )
        rows = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        analytics = next(row for row in rows if row.keyword == "analytics")
        assert analytics.clicks == 100 and analytics.impressions == 1000
        assert analytics.position == 8.2 and analytics.ctr == 0.1
        assert analytics.cost is None and analytics.conversions is None and analytics.cpc is None
        assert analytics.previous is not None and analytics.previous.position == 4
        query.breakdown = Breakdown1.PAGE
        query.keyword = "ANALYTICS"
        pages = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert {row.page for row in pages} == {"https://example.com/a", "https://example.com/b"}
        assert sum(row.clicks for row in pages) == 100
        query.breakdown = Breakdown1.KEYWORD
        query.keyword = None
        query.page = "https://example.com/a"
        queries = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results
        assert {row.keyword for row in queries} == {"analytics", "other"}
        assert sum(row.clicks for row in queries) == 15
        query.page = "https://example.com/a' OR 1=1 --"
        assert (
            MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate().results == []
        )

    @parameterized.expand(
        [
            (AttributionMode.LAST_TOUCH, 2, 1, False, SessionTableVersion.V2, False),
            (AttributionMode.LAST_TOUCH, 2, 1, False, SessionTableVersion.V2, True),
            (AttributionMode.LAST_TOUCH, 2, 1, False, SessionTableVersion.V3, False),
            (AttributionMode.LAST_TOUCH, 2, 1, False, SessionTableVersion.V3, True),
            (AttributionMode.FIRST_TOUCH, 3, 0, False, SessionTableVersion.V3, True),
            (AttributionMode.LAST_TOUCH, None, 1, True, SessionTableVersion.V2, True),
        ]
    )
    def test_posthog_landing_page_conversions_respect_source_model_filters_and_comparison(
        self,
        model: AttributionMode,
        paid_count: int | None,
        organic_count: int,
        multiple_currencies: bool,
        version: SessionTableVersion,
        shared_sessions: bool,
    ) -> None:
        self.team.modifiers = {"sessionTableVersion": version}
        self.team._ma_precompute_flags = {"conversion": False, "costs": False, "live_sessions": shared_sessions}  # type: ignore[attr-defined]
        config = self.team.marketing_analytics_config
        config.attribution_mode = model
        config.attribution_window_days = 7
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event="purchase",
                name="Purchases",
                conversion_goal_id="purchase-goal",
                conversion_goal_name="Purchases",
                schema_map={},
                math=BaseMathType.TOTAL,
                properties=[EventPropertyFilter(key="qualified", value=True, operator=PropertyOperator.EXACT)],
            ).model_dump()
        ]
        config.save()
        paid = self._table(
            "search_conversion_paid",
            {
                "landing_page_view_unexpanded_final_url": "String",
                "customer_currency_code": "String",
                "metrics_clicks": "Float64",
                "metrics_impressions": "Float64",
                "metrics_cost_micros": "Float64",
                "metrics_conversions": "Float64",
                "segments_date": "Date",
                "segments_ad_network_type": "String",
            },
            "landing_page_view_unexpanded_final_url,customer_currency_code,metrics_clicks,metrics_impressions,metrics_cost_micros,metrics_conversions,segments_date,segments_ad_network_type\n"
            "https://example.com/pricing?utm_campaign=spring,USD,20,100,40000000,5,2023-01-10,SEARCH\n"
            "https://example.com/pricing,USD,10,50,20000000,2,2023-01-10,SEARCH\n"
            "https://example.com/pricing,USD,5,20,8000000,1,2022-12-15,SEARCH\n"
            + ("https://example.com/pricing,EUR,3,10,6000000,1,2023-01-10,SEARCH\n" if multiple_currencies else ""),
        )
        organic = self._table(
            "search_conversion_organic",
            {
                "page": "String",
                "clicks": "Float64",
                "impressions": "Float64",
                "position": "Float64",
                "date": "Date",
            },
            "page,clicks,impressions,position,date\nhttps://example.com/pricing,40,200,2,2023-01-10\n",
        )
        bing = self._table(
            "search_conversion_bing",
            {
                "destination_url": "String",
                "currency_code": "String",
                "clicks": "Float64",
                "impressions": "Float64",
                "spend": "Float64",
                "conversions_qualified": "Float64",
                "time_period": "Date",
                "ad_distribution": "String",
            },
            "destination_url,currency_code,clicks,impressions,spend,conversions_qualified,time_period,ad_distribution\n"
            "https://example.com/pricing?utm_source=bing,USD,10,100,12,3,2023-01-10,Search\n"
            "https://example.com/pricing#plans,USD,5,50,8,2,2023-01-10,Search\n"
            "https://example.com/pricing,USD,3,30,6,1,2022-12-15,Search\n",
        )
        for person, day, url, medium, referrer, qualified in [
            ("paid", "2023-01-09", "https://example.com/pricing?utm_campaign=spring", "cpc", "$direct", True),
            ("journey", "2023-01-08", "https://example.com/pricing", "cpc", "$direct", True),
            ("other-host", "2023-01-09", "https://other.example.com/pricing", "cpc", "$direct", True),
            ("bing", "2023-01-09", "https://example.com/pricing", "", "www.bing.com", True),
            (
                "auto-tagged",
                "2023-01-09",
                "https://example.com/pricing?gclid=example-click",
                "cpc",
                "www.google.com",
                True,
            ),
            ("bing-paid", "2023-01-09", "https://example.com/pricing?utm_source=bing", "cpc", "www.bing.com", True),
            ("bing-previous", "2022-12-15", "https://example.com/pricing", "cpc", "www.bing.com", True),
            (
                "bing-auto-tagged",
                "2023-01-09",
                "https://example.com/pricing?msclkid=example-click",
                "cpc",
                "www.bing.com",
                True,
            ),
            ("bing-stored-click", "2022-12-15", "https://example.com/pricing", "cpc", "www.bing.com", True),
            ("excluded", "2023-01-09", "https://example.com/pricing", "cpc", "$direct", False),
            ("previous", "2022-12-15", "https://example.com/pricing", "cpc", "$direct", True),
        ]:
            create_person(team_id=self.team.pk, distinct_ids=[person])
            at = f"{day}T10:00:00Z"
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=person,
                timestamp=at,
                properties={
                    "$session_id": str(uuid7(at)),
                    "$current_url": url,
                    "$pathname": "/pricing",
                    "utm_source": (
                        "microsoft"
                        if person in ("bing-paid", "bing-previous")
                        else "google"
                        if medium and person not in ("auto-tagged", "bing-auto-tagged", "bing-stored-click")
                        else ""
                    ),
                    "gclid": "example-click" if person == "auto-tagged" else "",
                    "msclkid": "example-click" if person == "bing-stored-click" else "",
                    "utm_medium": medium,
                    "$referring_domain": referrer,
                },
            )
            _create_event(
                team=self.team,
                event="purchase",
                distinct_id=person,
                timestamp=f"{day}T13:00:00Z",
                properties={"qualified": qualified},
            )
        # The later organic touch earns last-touch credit, but not first-touch credit.
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="journey",
            timestamp="2023-01-08T11:00:00Z",
            properties={
                "$session_id": str(uuid7("2023-01-08T11:00:00Z")),
                "$current_url": "https://example.com/pricing#plans",
                "$pathname": "/pricing",
                "$referring_domain": "www.google.com",
            },
        )
        flush_persons_and_events()
        query = MarketingAnalyticsSearchQuery(
            sources=[
                MarketingAnalyticsSearchSource(sourceType="GoogleAds", statsTable=paid),
                MarketingAnalyticsSearchSource(sourceType="BingAds", statsTable=bing),
                MarketingAnalyticsSearchSource(sourceType="GoogleSearchConsole", statsTable=organic),
            ],
            breakdown="page",
            includePostHogConversions=True,
            compareFilter=CompareFilter(compare=True),
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
        )
        result = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate()
        assert len(result.results) == (4 if multiple_currencies else 3)
        assert bool(result.posthogConversionsWarning) == multiple_currencies
        assert result.posthogAttributionMode == model
        paid_row = next(row for row in result.results if row.platform == "GoogleAds" and row.currency == "USD")
        organic_row = next(row for row in result.results if row.platform == "GoogleSearchConsole")
        assert paid_row.conversions == 7
        assert paid_row.cost == 60
        assert paid_row.posthogConversions is not None
        assert paid_row.posthogConversions[0].conversions == paid_count
        assert paid_row.posthogConversions[0].costPerConversion == (60 / paid_count if paid_count else None)
        assert paid_row.posthogConversions[0].previousConversions == (None if multiple_currencies else 1)
        assert paid_row.posthogConversions[0].previousCostPerConversion == (None if multiple_currencies else 8)
        assert organic_row.posthogConversions is not None
        assert organic_row.posthogConversions[0].conversions == organic_count
        assert organic_row.posthogConversions[0].costPerConversion is None
        bing_row = next(row for row in result.results if row.platform == "BingAds")
        assert bing_row.page == "https://example.com/pricing"
        assert bing_row.cost == 20 and bing_row.conversions == 5
        assert bing_row.posthogConversions is not None
        assert bing_row.posthogConversions[0].conversions == 2
        assert bing_row.posthogConversions[0].costPerConversion == 10
        assert bing_row.posthogConversions[0].previousConversions == 2
        assert bing_row.posthogConversions[0].previousCostPerConversion == 3
        query.includePostHogConversions = False
        result = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).calculate()
        assert result.posthogConversionGoals is None
        assert all(row.posthogConversions is None for row in result.results)


class TestMarketingSearchConversionBudget(BaseTest):
    @parameterized.expand([(3, 3), (6, 5)])
    def test_bounds_goal_queries_and_reports_excluded_goals(self, goal_count: int, expected_count: int) -> None:
        config = self.team.marketing_analytics_config
        config.conversion_goals = [
            ConversionGoalFilter1(
                kind="EventsNode",
                event=None if index == 0 else "purchase",
                name=f"Goal {index}",
                conversion_goal_id=f"goal-{index}",
                conversion_goal_name=f"Goal {index}",
                schema_map={},
            ).model_dump()
            for index in range(goal_count + 1)
        ]
        config.save()
        metrics = MarketingAnalyticsSearchMetrics(clicks=1, impressions=10).model_dump()
        warehouse_row = {
            "page": "https://example.com/pricing",
            "platform": "GoogleSearchConsole",
            "currency_count": 1,
            **metrics,
            **{f"previous_{key}": value for key, value in metrics.items()},
        }
        with (
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_search_query_runner.execute_hogql_query",
                return_value=HogQLQueryResponse(columns=list(warehouse_row), results=[list(warehouse_row.values())]),
            ),
            patch(
                "products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner.execute_hogql_query",
                return_value=HogQLQueryResponse(results=[]),
            ) as execute_attribution,
            patch.object(Database, "create_for", wraps=Database.create_for) as create_database,
        ):
            result = MarketingAnalyticsSearchQueryRunner(
                query=MarketingAnalyticsSearchQuery(
                    sources=[MarketingAnalyticsSearchSource(sourceType="GoogleSearchConsole", statsTable="pages")],
                    breakdown="page",
                    includePostHogConversions=True,
                    compareFilter=CompareFilter(compare=True),
                    dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
                ),
                team=self.team,
                user=self.user,
            ).calculate()
        assert execute_attribution.call_count == expected_count * 2
        assert create_database.call_count == 1
        assert result.posthogConversionGoals is not None
        assert [goal.id for goal in result.posthogConversionGoals] == [
            f"goal-{index}" for index in range(1, expected_count + 1)
        ]
        conversions = result.results[0].posthogConversions
        assert conversions is not None and len(conversions) == expected_count
        assert all(goal.conversions == 0 and goal.previousConversions == 0 for goal in conversions)
        assert result.posthogConversionsWarning is not None
        assert "'All Events' cannot be used" in result.posthogConversionsWarning
        assert ("first 5 supported PostHog goals" in result.posthogConversionsWarning) == (goal_count > expected_count)


@pytest.mark.ee
class TestMarketingSearchCacheAccessControl(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.addCleanup(cache.clear)

    @parameterized.expand([True, False])
    def test_live_resolution_rollout_partitions_search_conversion_cache(self, include_conversions: bool) -> None:
        query = MarketingAnalyticsSearchQuery(
            sources=[], breakdown="page", includePostHogConversions=include_conversions
        )
        keys = []
        for enabled in (False, True, False):
            self.team._ma_precompute_flags = {"conversion": False, "costs": False, "live_sessions": enabled}  # type: ignore[attr-defined]
            keys.append(
                MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).get_cache_key()
            )
        assert (keys[0] != keys[1]) == include_conversions
        assert keys[0] == keys[2]

    @parameterized.expand(
        [
            ("warehouse_objects", {"warehouse_table", "warehouse_view"}),
            ("external_data_source", {"external_data_source"}),
        ]
    )
    def test_marketing_search_partitions_cache_on_warehouse_access_control(
        self, resource: str, expected_scopes: set[str]
    ) -> None:
        query = MarketingAnalyticsSearchQuery(
            sources=[MarketingAnalyticsSearchSource(sourceType="BingAds", statsTable="example.keyword_stats")]
        )
        access_control = AccessControl.objects.create(team=self.team, resource=resource, access_level="none")
        denied_runner = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user)
        assert expected_scopes.issubset(denied_runner.get_cache_payload().get("restricted_resources") or [])
        key_denied = denied_runner.get_cache_key()

        access_control.access_level = "editor"
        access_control.save()
        key_granted = MarketingAnalyticsSearchQueryRunner(query=query, team=self.team, user=self.user).get_cache_key()

        assert key_denied != key_granted
