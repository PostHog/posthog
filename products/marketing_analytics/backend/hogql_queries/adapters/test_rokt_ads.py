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
from .rokt_ads import RoktAdsAdapter


class TestRoktAdsAdapter(SimpleTestCase):
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

    def _adapter(self, currency: str | None) -> RoktAdsAdapter:
        source = ExternalDataSource(source_type="RoktAds", job_inputs={"currency_code": currency})
        table = DataWarehouseTable(
            name="example_roktads_campaignperformance",
            external_data_source=source,
            columns=dict.fromkeys(
                [
                    "campaign_id",
                    "campaign_name",
                    "datetime",
                    "impressions",
                    "referrals",
                    "gross_cost",
                    "net_cost",
                    "conversions",
                    "conversion_value",
                    "acquisitions",
                    "acquisitions_value",
                ],
                "String",
            ),
        )
        return RoktAdsAdapter(
            HierarchicalNativeAdsConfig(
                source_type="RoktAds",
                source_id="rokt-source",
                campaign_table=table,
                stats_table=table,
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

    @parameterized.expand([("configured", "GBP", "GBP"), ("default", None, "USD")])
    def test_report_is_aggregated_once_in_the_configured_currency(
        self, _name: str, currency: str | None, expected_currency: str
    ) -> None:
        adapter = self._adapter(currency)
        assert adapter.validate().is_valid
        for query in (adapter.build_query(), adapter.build_materialization_query("rokt-source")):
            assert query is not None
            sql = replace_placeholders(
                query,
                {
                    "time_window_min": ast.Constant(value="2026-09-01"),
                    "time_window_max": ast.Constant(value="2026-09-03"),
                },
            ).to_hogql()
            assert "JOIN" not in sql
            assert sql.count("FROM example_roktads_campaignperformance") == 1
            assert "example_roktads_campaignperformance.campaign_name" in sql
            assert "example_roktads_campaignperformance.gross_cost" in sql
            assert "example_roktads_campaignperformance.referrals" in sql
            assert "example_roktads_campaignperformance.conversion_value" in sql
            assert f"convertCurrency('{expected_currency}', 'EUR'" in sql
            assert "toDate(example_roktads_campaignperformance.datetime)" in sql
            assert "net_cost" not in sql
            assert "acquisitions" not in sql
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD_GROUP)

    def test_unavailable_conversion_metrics_are_zero(self) -> None:
        adapter = self._adapter(None)
        assert adapter.config.stats_table.columns is not None
        del adapter.config.stats_table.columns["conversions"]
        del adapter.config.stats_table.columns["conversion_value"]
        query = adapter.build_query()
        assert query is not None
        assert "0 AS reported_conversion" in query.to_hogql()

    def test_invalid_report_currency_is_rejected(self) -> None:
        assert not self._adapter("not-a-currency").validate().is_valid
