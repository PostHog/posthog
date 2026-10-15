from datetime import UTC, datetime

from unittest.mock import PropertyMock, patch

from django.test import SimpleTestCase

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.placeholders import replace_placeholders

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.warehouse_sources.backend.facade.models import DataWarehouseTable

from .amazon_ads import AmazonAdsAdapter
from .base import HierarchicalNativeAdsConfig, QueryContext


class TestAmazonAdsAdapter(SimpleTestCase):
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

    def _adapter(self) -> AmazonAdsAdapter:
        def table(name: str, fields: list[str]) -> DataWarehouseTable:
            return DataWarehouseTable(name=f"amazonads_{name}", columns=dict.fromkeys(fields, "String"))

        return AmazonAdsAdapter(
            HierarchicalNativeAdsConfig(
                source_type="AmazonAds",
                source_id="amazon-source",
                campaign_table=table("sp_campaigns", ["campaign_id", "name"]),
                stats_table=table(
                    "sp_campaign_reports",
                    [
                        "campaign_id",
                        "date",
                        "cost",
                        "spend",
                        "impressions",
                        "clicks",
                        "campaign_budget_currency_code",
                        "purchases14d",
                        "sales14d",
                        "purchases30d",
                        "sales30d",
                    ],
                ),
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
                drill_down_level=MarketingAnalyticsDrillDownLevel.CAMPAIGN,
            ),
        )

    def test_queries_use_one_attribution_window_and_dated_currency_conversion(self) -> None:
        adapter = self._adapter()
        assert adapter.validate().is_valid
        for query in (adapter.build_query(), adapter.build_materialization_query("amazon-source")):
            assert query is not None
            sql = replace_placeholders(
                query,
                {
                    "time_window_min": ast.Constant(value="2026-09-01"),
                    "time_window_max": ast.Constant(value="2026-09-03"),
                },
            ).to_hogql()
            assert "amazonads_sp_campaigns.campaign_id" in sql
            assert "amazonads_sp_campaign_reports.purchases14d" in sql
            assert "amazonads_sp_campaign_reports.sales14d" in sql
            assert "amazonads_sp_campaign_reports.campaign_budget_currency_code" in sql
            assert "toDate(amazonads_sp_campaign_reports.date)" in sql
            assert "'EUR'" in sql
            assert "purchases30d" not in sql
            assert "sales30d" not in sql
            assert "amazonads_sp_campaign_reports.spend" not in sql
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD_GROUP)
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD)

    def test_missing_optional_conversions_do_not_reference_absent_columns(self) -> None:
        adapter = self._adapter()
        assert adapter.config.stats_table.columns is not None
        del adapter.config.stats_table.columns["purchases14d"]
        del adapter.config.stats_table.columns["sales14d"]
        query = adapter.build_query()
        assert query is not None
        assert "0 AS reported_conversion" in query.to_hogql()
        assert "purchases14d" not in query.to_hogql()
        assert "sales14d" not in query.to_hogql()

    def test_missing_currency_is_invalid(self) -> None:
        adapter = self._adapter()
        assert adapter.config.stats_table.columns is not None
        del adapter.config.stats_table.columns["campaign_budget_currency_code"]
        assert not adapter.validate().is_valid
