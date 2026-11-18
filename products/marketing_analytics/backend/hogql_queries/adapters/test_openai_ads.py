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

from .base import HierarchicalNativeAdsConfig, QueryContext
from .openai_ads import OpenAIAdsAdapter


class TestOpenAIAdsAdapter(SimpleTestCase):
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

    def _adapter(self) -> OpenAIAdsAdapter:
        def table(name: str, fields: list[str]) -> DataWarehouseTable:
            return DataWarehouseTable(name=f"openaiads_{name}", columns=dict.fromkeys(fields, "String"))

        return OpenAIAdsAdapter(
            HierarchicalNativeAdsConfig(
                source_type="OpenAIAds",
                source_id="openai-source",
                campaign_table=table("campaigns", ["id", "name"]),
                stats_table=table(
                    "campaign_insights",
                    [
                        "campaign_id",
                        "start_time",
                        "spend",
                        "impressions",
                        "clicks",
                        "currency_code",
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

    def test_queries_convert_spend_without_treating_it_as_micros(self) -> None:
        adapter = self._adapter()
        assert adapter.validate().is_valid
        for query in (adapter.build_query(), adapter.build_materialization_query("openai-source")):
            assert query is not None
            sql = replace_placeholders(
                query,
                {
                    "time_window_min": ast.Constant(value="2026-09-01"),
                    "time_window_max": ast.Constant(value="2026-09-03"),
                },
            ).to_hogql()
            assert "openaiads_campaigns.id" in sql
            assert "openaiads_campaign_insights.campaign_id" in sql
            assert "openaiads_campaign_insights.spend" in sql
            assert "openaiads_campaign_insights.currency_code" in sql
            assert "toDate(openaiads_campaign_insights.start_time)" in sql
            assert "'EUR'" in sql
            assert "1000000" not in sql
            assert "countIf(empty(coalesce(openaiads_campaign_insights.currency_code, '')))" in sql
            assert "throwIf(" in sql
            assert "Fully resync campaign_insights" in sql
            assert "0 AS reported_conversion" in sql
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD_GROUP)

    def test_old_sync_without_currency_is_invalid(self) -> None:
        adapter = self._adapter()
        assert adapter.config.stats_table.columns is not None
        del adapter.config.stats_table.columns["currency_code"]
        assert not adapter.validate().is_valid
