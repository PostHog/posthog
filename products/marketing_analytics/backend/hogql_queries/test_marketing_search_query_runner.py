from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.schema import CompareFilter, DateRange, MarketingAnalyticsSearchQuery, MarketingAnalyticsSearchSource

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
