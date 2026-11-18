from datetime import UTC, datetime

from unittest.mock import PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.placeholders import replace_placeholders

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

from .apple_search_ads import AppleSearchAdsAdapter
from .base import HierarchicalNativeAdsConfig, QueryContext


class TestAppleSearchAdsAdapter(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=1)
        self.enterContext(
            patch.object(
                Team,
                "marketing_analytics_config",
                new_callable=PropertyMock,
                return_value=TeamMarketingAnalyticsConfig(team=self.team),
            )
        )

    def _adapter(self, columns: list[str], level: MarketingAnalyticsDrillDownLevel) -> AppleSearchAdsAdapter:
        def table(name: str, fields: list[str]) -> DataWarehouseTable:
            return DataWarehouseTable(name=f"applesearchads_{name}", columns=dict.fromkeys(fields, "String"))

        metrics = ["date", "impressions", "taps", "local_spend", *columns]
        return AppleSearchAdsAdapter(
            HierarchicalNativeAdsConfig(
                source_type="AppleSearchAds",
                source_id="apple-source",
                campaign_table=table("campaigns", ["id", "name"]),
                stats_table=table("campaign_report", ["campaign_id", *metrics]),
                adset_table=table("ad_groups", ["id", "name", "campaign_id"]),
                adset_stats_table=table("ad_group_report", ["ad_group_id", *metrics]),
            ),
            QueryContext(
                team=self.team,
                date_range=QueryDateRange(
                    date_range=DateRange(date_from="2026-09-01", date_to="2026-09-02"),
                    team=self.team,
                    interval=None,
                    now=datetime(2026, 9, 3, tzinfo=UTC),
                ),
                base_currency="EUR",
                drill_down_level=level,
            ),
        )

    @parameterized.expand(
        [
            ("v5", ["installs"], "installs"),
            ("v1", ["total_installs"], "total_installs"),
            ("repinned", ["total_installs", "installs"], "total_installs"),
        ]
    )
    def test_campaign_queries_use_daily_money_and_versioned_installs(
        self, _name: str, columns: list[str], conversion_column: str
    ) -> None:
        adapter = self._adapter(columns, MarketingAnalyticsDrillDownLevel.CAMPAIGN)
        assert adapter.validate().is_valid
        for query in (adapter.build_query(), adapter.build_materialization_query("apple-source")):
            assert query is not None
            sql = replace_placeholders(
                query,
                {
                    "time_window_min": ast.Constant(value="2026-09-01"),
                    "time_window_max": ast.Constant(value="2026-09-03"),
                },
            ).to_hogql()
            assert "applesearchads_campaign_report.local_spend['amount']" in sql
            assert "applesearchads_campaign_report.local_spend['currency']" in sql
            assert "'EUR'" in sql
            assert "toDate(applesearchads_campaign_report.date)" in sql
            assert f"applesearchads_campaign_report.{conversion_column}" in sql
            assert "applesearchads_campaign_report.taps" in sql
            if len(columns) == 2:
                assert (
                    "coalesce(toFloat(applesearchads_campaign_report.total_installs), toFloat(applesearchads_campaign_report.installs), 0)"
                    in sql
                )

    def test_ad_group_query_joins_campaign_and_uses_ad_group_report(self) -> None:
        adapter = self._adapter(["total_installs"], MarketingAnalyticsDrillDownLevel.AD_GROUP)
        assert adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD_GROUP)
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD)
        query = adapter.build_query()
        assert query is not None
        sql = query.to_hogql()
        assert "applesearchads_ad_group_report.ad_group_id" in sql
        assert "applesearchads_ad_groups.campaign_id" in sql
        assert "applesearchads_ad_group_report.local_spend['amount']" in sql
        assert "applesearchads_campaign_report" not in sql

    @parameterized.expand(
        [
            (MarketingAnalyticsDrillDownLevel.CAMPAIGN, "stats_table", "local_spend"),
            (MarketingAnalyticsDrillDownLevel.AD_GROUP, "adset_table", "campaign_id"),
            (MarketingAnalyticsDrillDownLevel.AD_GROUP, "campaign_table", "id"),
            (MarketingAnalyticsDrillDownLevel.AD_GROUP, "campaign_table", "name"),
        ]
    )
    def test_missing_required_columns_are_reported_as_invalid(
        self, level: MarketingAnalyticsDrillDownLevel, table_name: str, column: str
    ) -> None:
        adapter = self._adapter(["total_installs"], level)
        table = getattr(adapter.config, table_name)
        assert table.columns is not None
        del table.columns[column]
        result = adapter.validate()
        assert not result.is_valid
        assert column in result.errors[0]
