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

from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource

from .base import HierarchicalNativeAdsConfig, QueryContext
from .twitter_ads import TwitterAdsAdapter

_CAMPAIGN_COLUMNS = ["id", "name", "funding_instrument_id", "deleted"]
_LINE_ITEM_COLUMNS = ["id", "name", "campaign_id", "objective"]
_STATS_COLUMNS = [
    "entity_id",
    "date",
    "placement",
    "currency",
    "impressions",
    "clicks",
    "billed_charge_local_micro",
    "account_id",
]


class TestTwitterAdsAdapter(SimpleTestCase):
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

    def _table(self, name: str, columns: list[str]) -> DataWarehouseTable:
        return DataWarehouseTable(
            name=name,
            external_data_source=ExternalDataSource(source_type="TwitterAds"),
            columns=dict.fromkeys(columns, "String"),
        )

    def _adapter(self, drill_down_level: MarketingAnalyticsDrillDownLevel) -> TwitterAdsAdapter:
        return TwitterAdsAdapter(
            HierarchicalNativeAdsConfig(
                source_type="TwitterAds",
                source_id="x-source",
                campaign_table=self._table("twitterads_campaigns", _CAMPAIGN_COLUMNS),
                stats_table=self._table("twitterads_campaign_stats", _STATS_COLUMNS),
                adset_table=self._table("twitterads_line_items", _LINE_ITEM_COLUMNS),
                adset_stats_table=self._table("twitterads_line_item_stats", _STATS_COLUMNS),
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
                drill_down_level=drill_down_level,
            ),
        )

    def _sql(self, adapter: TwitterAdsAdapter) -> str:
        query = adapter.build_query()
        assert query is not None
        return replace_placeholders(
            query,
            {
                "time_window_min": ast.Constant(value="2026-09-01"),
                "time_window_max": ast.Constant(value="2026-09-03"),
            },
        ).to_hogql()

    def test_campaign_spend_is_converted_from_micros_at_the_row_currency(self) -> None:
        sql = self._sql(self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN))

        assert "divide(coalesce(toFloat(twitterads_campaign_stats.billed_charge_local_micro), 0), 1000000)" in sql
        assert "convertCurrency(coalesce(twitterads_campaign_stats.currency, 'EUR'), 'EUR'" in sql
        assert "toDate(twitterads_campaign_stats.date)" in sql
        assert "throwIf(greater(countIf(empty(coalesce(twitterads_campaign_stats.currency, ''))), 0)" in sql

    def test_campaign_level_joins_stats_on_entity_id(self) -> None:
        sql = self._sql(self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN))

        assert "twitterads_campaign_stats.entity_id" in sql
        assert "twitterads_campaigns.id" in sql
        assert "twitterads_campaigns.name" in sql

    def test_ad_group_level_reads_the_line_item_tables(self) -> None:
        sql = self._sql(self._adapter(MarketingAnalyticsDrillDownLevel.AD_GROUP))

        assert "twitterads_line_item_stats" in sql
        assert "twitterads_line_items" in sql
        assert "twitterads_line_item_stats.entity_id" in sql

    def test_metrics_aggregate_so_placements_add_up(self) -> None:
        sql = self._sql(self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN))

        assert "sum(coalesce(toFloat(twitterads_campaign_stats.impressions), 0))" in sql
        assert "sum(coalesce(toFloat(twitterads_campaign_stats.clicks), 0))" in sql

    def test_conversions_report_zero_until_the_source_requests_them(self) -> None:
        sql = self._sql(self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN))

        assert "0 AS reported_conversion" in sql

    def test_validation_passes_on_a_complete_schema(self) -> None:
        assert self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN).validate().is_valid

    @parameterized.expand([("currency",), ("billed_charge_local_micro",)])
    def test_stats_table_without_required_column_is_rejected(self, column: str) -> None:
        adapter = self._adapter(MarketingAnalyticsDrillDownLevel.CAMPAIGN)
        assert adapter.config.stats_table.columns is not None
        del adapter.config.stats_table.columns[column]

        result = adapter.validate()
        assert not result.is_valid
        assert any(column in error for error in result.errors)
