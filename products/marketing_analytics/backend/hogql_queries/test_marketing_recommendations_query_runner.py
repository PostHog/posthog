from pathlib import Path
from tempfile import TemporaryDirectory

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsRecommendationsQuery, MarketingAnalyticsRecommendationsSource

from posthog.models.utils import uuid7

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations_query_runner import (
    MarketingAnalyticsRecommendationsQueryRunner,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

PURCHASE = "customers/1/conversionActions/10"
SIGNUP = "customers/1/conversionActions/20"
MANAGER_SIGNUP = "customers/9/conversionActions/20"
BOTH_SPLITS = ("campaign", "search_term")
SESSION_START_MS = 1768478400000  # 2026-01-15 12:00 UTC


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
                "customer_id": "Int64",
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
                    "1234567890",
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

        budget = [
            (rec.subject, rec.action, rec.identity.customer_id, rec.identity.campaign_id)
            for rec in response.results
            if rec.rule == "budget_constrained"
        ]
        assert budget == (
            [("Campaign 101", "Raise the daily budget from $100 to $300", "1234567890", "101")] if has_status else []
        )

    def test_ranking_page_is_the_page_with_most_impressions_for_the_query(self) -> None:
        query_page = self._table(
            "search_analytics_by_query_page",
            {"date": "Date", "query": "String", "page": "String", "impressions": "Float64"},
            "date,query,page,impressions\n"
            "2026-01-10,Funnel Analysis,https://example.com/blog,600\n"
            "2026-01-11,funnel analysis,https://example.com/funnels,400\n"
            "2026-01-12,funnel analysis,https://example.com/funnels,400\n"
            "2025-12-01,funnel analysis,https://example.com/old,5000\n",
        )
        runner = MarketingAnalyticsRecommendationsQueryRunner(
            query=MarketingAnalyticsRecommendationsQuery(
                dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-30")
            ),
            team=self.team,
            user=self.user,
        )

        pages = runner._ranking_pages(
            MarketingAnalyticsRecommendationsSource(sourceType="GoogleSearchConsole", queryPageTable=query_page)
        )

        assert [(page.query, page.page) for page in pages] == [("funnel analysis", "https://example.com/funnels")]

    @parameterized.expand(
        [
            ("primary_actions_by_default", None, BOTH_SPLITS, "alpha", 100.0, "target_cpa", []),
            ("selected_secondary_action", [SIGNUP], BOTH_SPLITS, "beta", 200.0, "account", []),
            ("no_split_tables", [SIGNUP], (), "alpha", 100.0, "target_cpa", ["conversion_action_tables_not_synced"]),
            (
                "only_campaign_split",
                [SIGNUP],
                ("campaign",),
                "alpha",
                100.0,
                "target_cpa",
                ["conversion_action_tables_not_synced"],
            ),
            (
                "another_accounts_action",
                ["customers/2/conversionActions/20"],
                BOTH_SPLITS,
                "alpha",
                100.0,
                "target_cpa",
                [],
            ),
            ("manager_account_action", [MANAGER_SIGNUP], BOTH_SPLITS, "beta", 200.0, "account", [], MANAGER_SIGNUP),
            (
                "performance_max_terms_without_performance_max_campaigns",
                [SIGNUP],
                (*BOTH_SPLITS, "performance_max"),
                "beta",
                200.0,
                "account",
                [],
            ),
        ]
    )
    def test_counts_only_the_selected_conversion_actions(
        self,
        _name: str,
        conversion_actions: list[str] | None,
        split_tables: tuple[str, ...],
        wasted_term: str,
        best_campaign_cpa: float,
        benchmark_source: str,
        gaps: list[str],
        signup: str = SIGNUP,
    ) -> None:
        campaigns = self._table(
            "campaign",
            {
                "campaign_id": "Int64",
                "customer_id": "Int64",
                "campaign_name": "String",
                "campaign_advertising_channel_type": "String",
                "campaign_budget_amount_micros": "Int64",
                "campaign_target_cpa_target_cpa_micros": "Int64",
            },
            "campaign_id,customer_id,campaign_name,campaign_advertising_channel_type,campaign_budget_amount_micros,"
            "campaign_target_cpa_target_cpa_micros\n1,1,Search,SEARCH,100000000,150000000\n",
        )
        stats = self._table(
            "campaign_stats",
            {
                "campaign_id": "Int64",
                "segments_date": "Date",
                "metrics_cost_micros": "Int64",
                "metrics_conversions": "Float64",
            },
            "campaign_id,segments_date,metrics_cost_micros,metrics_conversions\n1,2026-01-15,1000000000,10\n",
        )
        term_columns = {
            "search_term_view_search_term": "String",
            "campaign_id": "Int64",
            "segments_date": "Date",
            "metrics_clicks": "Int64",
            "metrics_impressions": "Int64",
            "metrics_cost_micros": "Int64",
            "metrics_conversions": "Float64",
            "search_term_view_status": "String",
        }
        terms = self._table(
            "search_term_stats",
            term_columns,
            ",".join(term_columns)
            + "\nalpha,1,2026-01-15,10,100,500000000,0,NONE\nbeta,1,2026-01-15,10,100,500000000,10,NONE\n",
        )
        source = MarketingAnalyticsRecommendationsSource(
            sourceType="GoogleAds", campaignTable=campaigns, campaignStatsTable=stats, searchTermTable=terms
        )
        action_columns = {
            "campaign_id": "Int64",
            "segments_date": "Date",
            "segments_conversion_action": "String",
            "metrics_conversions": "Float64",
            "metrics_all_conversions": "Float64",
        }
        # Purchase is the primary action. Signup is secondary, so only all_conversions counts it.
        if "campaign" in split_tables:
            source.campaignConversionActionTable = self._table(
                "campaign_conversion_action_stats",
                action_columns,
                ",".join(action_columns) + f"\n1,2026-01-15,{PURCHASE},10,10\n1,2026-01-15,{signup},0,5\n",
            )
        if "search_term" in split_tables:
            term_action_columns = {"search_term_view_search_term": "String", **action_columns}
            source.searchTermConversionActionTable = self._table(
                "search_term_conversion_action_stats",
                term_action_columns,
                ",".join(term_action_columns)
                + f"\nbeta,1,2026-01-15,{PURCHASE},10,10\nalpha,1,2026-01-15,{signup},0,5\n",
            )
        if "performance_max" in split_tables:
            pmax_columns = {
                "campaign_search_term_view_search_term": "String",
                "campaign_id": "Int64",
                "segments_date": "Date",
                "metrics_clicks": "Int64",
                "metrics_impressions": "Int64",
                "metrics_cost_micros": "Int64",
                "metrics_conversions": "Float64",
            }
            source.performanceMaxSearchTermTable = self._table(
                "performance_max_search_term_stats", pmax_columns, ",".join(pmax_columns) + "\n"
            )

        response = MarketingAnalyticsRecommendationsQueryRunner(
            query=MarketingAnalyticsRecommendationsQuery(
                dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-30"),
                sources=[source],
                conversionActions=conversion_actions,
            ),
            team=self.team,
            user=self.user,
        ).calculate()

        wasted = [rec for rec in response.results if rec.rule == "spend_without_conversions"]
        assert [rec.subject for rec in wasted] == [wasted_term]
        assert wasted[0].cpa is not None and wasted[0].cpa.bestCampaign == best_campaign_cpa
        assert wasted[0].cpa.benchmarkSource == benchmark_source
        assert [gap.kind for gap in response.dataGaps or []] == gaps

    @parameterized.expand(
        [
            ("suffix_without_keyword", "utm_source=google", "", ["Acme Ads"]),
            ("suffix_with_keyword", "utm_source=google&utm_term={keyword}", "", []),
            ("campaign_template_with_keyword", "utm_source=google", "{lpurl}?utm_term={keyword}", []),
            ("customer_table_not_synced", None, "", ["Google Ads account"]),
        ]
    )
    def test_keyword_tracking_reads_google_ads_sessions_and_account_settings(
        self, _name: str, suffix: str | None, campaign_template: str, expected: list[str]
    ) -> None:
        campaigns = self._table(
            "campaign",
            {
                "campaign_id": "Int64",
                "campaign_name": "String",
                "campaign_advertising_channel_type": "String",
                "campaign_budget_amount_micros": "Int64",
                "campaign_tracking_url_template": "String",
            },
            "campaign_id,campaign_name,campaign_advertising_channel_type,campaign_budget_amount_micros,"
            f"campaign_tracking_url_template\n1,Search,SEARCH,100000000,{campaign_template}\n",
        )
        stats = self._table(
            "campaign_stats",
            {
                "campaign_id": "Int64",
                "segments_date": "Date",
                "metrics_cost_micros": "Int64",
                "metrics_conversions": "Float64",
            },
            "campaign_id,segments_date,metrics_cost_micros,metrics_conversions\n1,2026-01-15,1000000000,10\n",
        )
        customer = (
            self._table(
                "customer",
                {"customer_descriptive_name": "String", "customer_final_url_suffix": "String"},
                f"customer_descriptive_name,customer_final_url_suffix\nAcme Ads,{suffix}\n",
            )
            if suffix is not None
            else None
        )
        # Only the sessions with a gclid count, so the organic visits with utm_term must not hide the gap.
        for i in range(40):
            properties = {"$session_id": str(uuid7(SESSION_START_MS + i)), "$current_url": "https://example.com"}
            if i < 30:
                properties["gclid"] = f"click{i}"
            else:
                properties["utm_term"] = "organic"
            _create_event(
                team=self.team, event="$pageview", distinct_id=f"user{i}", timestamp="2026-01-15", properties=properties
            )
        flush_persons_and_events()

        response = MarketingAnalyticsRecommendationsQueryRunner(
            query=MarketingAnalyticsRecommendationsQuery(
                dateRange=DateRange(date_from="2026-01-01", date_to="2026-01-30"),
                sources=[
                    MarketingAnalyticsRecommendationsSource(
                        sourceType="GoogleAds",
                        campaignTable=campaigns,
                        campaignStatsTable=stats,
                        customerTable=customer,
                    )
                ],
            ),
            team=self.team,
            user=self.user,
        ).calculate()

        assert [rec.subject for rec in response.results if rec.rule == "keyword_tracking"] == expected


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
            {
                "campaign": True,
                "campaign_stats": True,
                "search_term_stats": True,
                "search_term_conversion_action_stats": True,
                "customer": False,
            },
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
                "searchTermConversionActionTable": "googleads.acme.search_term_conversion_action_stats",
            },
            {
                "sourceType": "GoogleSearchConsole",
                "queryTable": "googlesearchconsole.organic.search_analytics_by_query_page",
                "queryPageTable": "googlesearchconsole.organic.search_analytics_by_query_page",
                "sitesTable": "googlesearchconsole.organic.sites",
            },
        ]
