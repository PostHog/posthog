from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsRecommendationsQuery, MarketingAnalyticsRecommendationsSource

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations_query_runner import (
    MarketingAnalyticsRecommendationsQueryRunner,
)
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv


class TestMarketingAnalyticsRecommendationsQueryRunner(ClickhouseTestMixin, BaseTest):
    def _table(self, name: str, columns: dict[str, str], csv: str) -> str:
        with TemporaryDirectory() as directory:
            path = Path(directory) / f"{name}.csv"
            path.write_text(csv)
            table, _, _, _, cleanup = create_data_warehouse_table_from_csv(
                path, name, columns, f"test_storage_bucket-posthog.marketing_analytics.{name}", self.team
            )
        self.addCleanup(cleanup)
        return table.name

    @parameterized.expand([("with_status_columns", True), ("before_status_columns_were_synced", False)])
    def test_reads_every_campaign_and_tolerates_missing_status_columns(self, _name: str, has_status: bool) -> None:
        count = 101
        campaign_columns = {
            "campaign_id": "Int64",
            "campaign_name": "String",
            "campaign_advertising_channel_type": "String",
            "campaign_budget_amount_micros": "Int64",
        }
        if has_status:
            campaign_columns |= {
                "campaign_primary_status": "String",
                "campaign_primary_status_reasons": "String",
                "campaign_budget_recommended_budget_amount_micros": "Int64",
            }
        rows = []
        for i in range(1, count + 1):
            row = [str(i), f"Campaign {i}", "SEARCH", "100000000"]
            if has_status:
                constrained = i == count
                row += [
                    "LIMITED" if constrained else "ELIGIBLE",
                    '"[""BUDGET_CONSTRAINED""]"' if constrained else '"[]"',
                    "300000000" if constrained else "0",
                ]
            rows.append(",".join(row))
        campaigns = self._table(
            "campaign", campaign_columns, ",".join(campaign_columns) + "\n" + "\n".join(rows) + "\n"
        )
        stats = self._table(
            "campaign_stats",
            {
                "campaign_id": "Int64",
                "segments_date": "Date",
                "metrics_cost_micros": "Int64",
                "metrics_conversions": "Float64",
            },
            "campaign_id,segments_date,metrics_cost_micros,metrics_conversions\n"
            + "".join(f"{i},2026-01-15,1000000000,10\n" for i in range(1, count + 1)),
        )

        response = MarketingAnalyticsRecommendationsQueryRunner(
            query=MarketingAnalyticsRecommendationsQuery(
                dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-30"),
                sources=[
                    MarketingAnalyticsRecommendationsSource(
                        sourceType="GoogleAds", campaignTable=campaigns, campaignStatsTable=stats
                    )
                ],
            ),
            team=self.team,
            user=self.user,
        ).calculate()

        budget = [(rec.subject, rec.action) for rec in response.results if rec.rule == "budget_constrained"]
        assert budget == ([("Campaign 101", "Raise the daily budget from $100 to $300")] if has_status else [])
