from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsRecommendationsQuery, MarketingAnalyticsRecommendationsSource

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations_query_runner import (
    MarketingAnalyticsRecommendationsQueryRunner,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
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


class TestMarketingAnalyticsRecommendationsSourceDiscovery(BaseTest):
    def _source(self, source_type: str, prefix: str, schemas: dict[str, bool]) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=prefix,
            connection_id=prefix,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=source_type,
            prefix=prefix,
        )
        for name, synced in schemas.items():
            table = DataWarehouseTable.objects.create(
                team=self.team, name=f"{prefix}{source_type.lower()}_{name}", columns={}, external_data_source=source
            )
            ExternalDataSchema.objects.create(
                team=self.team,
                source=source,
                name=name,
                table=table,
                should_sync=synced,
                last_synced_at=timezone.now() if synced else None,
            )

    def test_reads_synced_tables_of_every_google_source_when_the_query_names_none(self) -> None:
        self._source(
            "GoogleAds",
            "acme",
            {"campaign": True, "campaign_stats": True, "search_term_stats": True, "customer": False},
        )
        self._source("GoogleAds", "unsynced", {"campaign": True, "campaign_stats": False})
        self._source("GoogleSearchConsole", "organic", {"search_analytics_by_query_page": True, "sites": True})
        self._source("BingAds", "bing", {"campaign_performance_report": True})

        runner = MarketingAnalyticsRecommendationsQueryRunner(
            query=MarketingAnalyticsRecommendationsQuery(), team=self.team, user=self.user
        )

        sources = sorted(runner._project_sources(), key=lambda source: source.sourceType)
        assert [source.model_dump(exclude_none=True) for source in sources] == [
            {
                "sourceType": "GoogleAds",
                "campaignTable": "googleads.acme.campaign",
                "campaignStatsTable": "googleads.acme.campaign_stats",
                "searchTermTable": "googleads.acme.search_term_stats",
            },
            {
                "sourceType": "GoogleSearchConsole",
                "queryTable": "googlesearchconsole.organic.search_analytics_by_query_page",
                "sitesTable": "googlesearchconsole.organic.sites",
            },
        ]
