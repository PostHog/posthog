import uuid
from datetime import date, datetime
from pathlib import Path

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from django.test import override_settings

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel, MarketingAnalyticsTableQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.preaggregation.marketing_costs_sql import DISTRIBUTED_MARKETING_COSTS_TABLE
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.marketing_analytics.backend.hogql_queries.adapters.base import (
    GoogleAdsConfig,
    MarketingSourceAdapter,
    QueryContext,
)
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.google_ads import GoogleAdsAdapter
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_table_query_runner import (
    MarketingAnalyticsTableQueryRunner,
)
from products.warehouse_sources.backend.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_marketing_costs"

# Wide range so we capture every CSV row; the direct read uses the same range.
WIDE_FROM = "2000-01-01"
WIDE_TO = "2100-01-01"

GOOGLE_CAMPAIGN_COLUMNS: dict[str, dict[str, str | bool]] = {
    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
    "campaign_name": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
    "campaign_status": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
}
GOOGLE_STATS_COLUMNS: dict[str, dict[str, str | bool]] = {
    "campaign_id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
    "segments_date": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
    "metrics_clicks": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
    "metrics_cost_micros": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
    "metrics_impressions": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
    "metrics_conversions": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
    "metrics_conversions_value": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
}


@override_settings(IN_UNIT_TESTING=True)
class TestMarketingCostsPrecompute(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        base = Path(__file__).parent
        campaign_table, *_rest, cleanup_c = create_data_warehouse_table_from_csv(
            base / "test/google_ads/campaign.csv",
            "google_ads_campaign_table",
            GOOGLE_CAMPAIGN_COLUMNS,
            f"{TEST_BUCKET}.campaign",
            self.team,
        )
        stats_table, *_rest2, cleanup_s = create_data_warehouse_table_from_csv(
            base / "test/google_ads/campaign_stats.csv",
            "google_ads_stats_table",
            GOOGLE_STATS_COLUMNS,
            f"{TEST_BUCKET}.stats",
            self.team,
        )
        self.addCleanup(cleanup_c)
        self.addCleanup(cleanup_s)
        self._campaign_table = campaign_table
        self._stats_table = stats_table

    def _adapter(self) -> GoogleAdsAdapter:
        config = GoogleAdsConfig(
            campaign_table=self._campaign_table,
            stats_table=self._stats_table,
            source_type="GoogleAds",
            source_id="google_test",
        )
        context = QueryContext(
            date_range=QueryDateRange(
                date_range=DateRange(date_from=WIDE_FROM, date_to=WIDE_TO),
                team=self.team,
                interval=None,
                now=datetime(2025, 1, 1),
            ),
            team=self.team,
            base_currency=self.team.base_currency or "USD",
            drill_down_level=MarketingAnalyticsDrillDownLevel.CAMPAIGN,
        )
        return GoogleAdsAdapter(config=config, context=context)

    def _execute(self, query: ast.Expr) -> tuple[list, list[str]]:
        result = execute_hogql_query(query.to_hogql(), self.team)
        return (result.results or [], list(result.columns or []))

    def _col(self, columns: list[str], name: str) -> int:
        return columns.index(name)

    def test_materialization_total_matches_direct_read(self):
        adapter = self._adapter()

        direct_query = adapter.build_query()
        assert direct_query is not None
        direct_rows, direct_cols = self._execute(direct_query)

        mat = adapter.build_materialization_query("google_test")
        assert mat is not None
        mat_query = replace_placeholders(
            mat,
            {"time_window_min": ast.Constant(value=WIDE_FROM), "time_window_max": ast.Constant(value=WIDE_TO)},
        )
        mat_rows, mat_cols = self._execute(mat_query)

        assert direct_rows, "direct read returned no rows — seed/CSV problem"
        assert mat_rows, "materialization returned no rows"

        # Per-day materialized cost, summed, must equal the direct (already campaign-summed) cost.
        direct_cost = sum(float(r[self._col(direct_cols, "cost")]) for r in direct_rows)
        mat_cost = sum(float(r[self._col(mat_cols, "cost")]) for r in mat_rows)
        assert abs(direct_cost - mat_cost) < 1e-6, f"cost diverged: direct={direct_cost} mat={mat_cost}"

    def test_materialization_populates_source_id_grain_and_date(self):
        adapter = self._adapter()
        mat = adapter.build_materialization_query("google_test")
        assert mat is not None
        mat_query = replace_placeholders(
            mat,
            {"time_window_min": ast.Constant(value=WIDE_FROM), "time_window_max": ast.Constant(value=WIDE_TO)},
        )
        rows, cols = self._execute(mat_query)
        assert rows

        source_ids = {r[self._col(cols, "source_id")] for r in rows}
        grains = {r[self._col(cols, "grain")] for r in rows}
        sources = {r[self._col(cols, "source_name")] for r in rows}
        assert source_ids == {"google_test"}
        assert grains == {"campaign"}
        assert sources == {"google"}
        # cost_date is a real per-day date (not the sentinel empty), enabling daily-window caching.
        assert all(r[self._col(cols, "cost_date")] is not None for r in rows)

    def test_native_read_takes_latest_job_per_cell_not_sum(self):
        # The same (campaign, day) cell materialized under two job_ids — a stale value and a matured one.
        # job_id is in the ReplacingMergeTree sort key, so both rows survive; the read must return the
        # latest-computed value (argMax), not their sum, even when both job_ids are read together.
        cell = {
            "source_id": "google_test",
            "source_name": "google",
            "grain": "campaign",
            "match_key": "c1",
            "campaign_id": "c1",
            "campaign_name": "Camp 1",
            "cost_date": date(2023, 1, 15),
        }
        job_old, job_new = str(uuid.uuid4()), str(uuid.uuid4())
        rows = [
            (
                self.team.pk,
                job,
                cell["source_id"],
                cell["source_name"],
                cell["grain"],
                cell["match_key"],
                cell["campaign_id"],
                cell["campaign_name"],
                "",
                "",
                "",
                "",
                cell["cost_date"],
                cost,
                0.0,
                0.0,
                0.0,
                0.0,
                computed_at,
                date(2099, 1, 1),
            )
            for job, cost, computed_at in (
                (job_old, 100.0, datetime(2023, 1, 15, 10, 0)),
                (job_new, 150.0, datetime(2023, 1, 16, 10, 0)),
            )
        ]
        sync_execute(
            f"INSERT INTO {DISTRIBUTED_MARKETING_COSTS_TABLE()} "
            "(team_id, job_id, source_id, source_name, grain, match_key, campaign_id, campaign_name, "
            "ad_group_id, ad_group_name, ad_id, ad_name, cost_date, cost, clicks, impressions, "
            "reported_conversions, reported_conversion_value, computed_at, expires_at) VALUES",
            rows,
        )

        date_range = DateRange(date_from="2023-01-01", date_to="2023-01-31")
        runner = MarketingAnalyticsTableQueryRunner(
            query=MarketingAnalyticsTableQuery(dateRange=date_range, limit=100, offset=0, properties=[]),
            team=self.team,
        )
        read = runner._costs_native_read_query(
            [job_old, job_new],
            MarketingAnalyticsDrillDownLevel.CAMPAIGN,
            QueryDateRange(date_range=date_range, team=self.team, interval=None, now=datetime(2025, 1, 1)),
        )
        result_rows, result_cols = self._execute(read)
        total_cost = sum(float(r[self._col(result_cols, MarketingSourceAdapter.cost_field)]) for r in result_rows)
        assert total_cost == 150.0, f"expected latest job cost 150 (argMax), got {total_cost} (sum would be 250)"

    def test_one_unmaterializable_source_does_not_force_all_to_s3(self):
        # One source materializes, one can't. The result must read the native table for the materialized
        # source and keep only the other on the live S3 union — not fall back to S3 for everything.
        runner = MarketingAnalyticsTableQueryRunner(
            query=MarketingAnalyticsTableQuery(
                dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"), limit=100, offset=0, properties=[]
            ),
            team=self.team,
        )
        runner.config.costs_precomputation_enabled = True

        good = Mock()
        good.get_source_id.return_value = "good"
        good.supports_level.return_value = True
        good.config.source_id = "good"
        good.build_materialization_query.return_value = parse_select("SELECT 1")

        bad = Mock()
        bad.get_source_id.return_value = "bad"
        bad.supports_level.return_value = True
        bad.config.source_id = "bad"
        bad.build_materialization_query.return_value = None  # cannot materialize -> stays on S3
        bad.build_query.return_value = parse_select("SELECT 'live_s3_marker' AS source")

        date_range = QueryDateRange(
            date_range=DateRange(date_from="2023-01-01", date_to="2023-01-31"),
            team=self.team,
            interval=None,
            now=datetime(2023, 2, 1),
        )
        ready = Mock(ready=True, job_ids=["00000000-0000-0000-0000-000000000001"])
        with (
            patch.object(MarketingSourceFactory, "create_adapters", lambda self: [good, bad]),
            patch.object(MarketingSourceFactory, "get_valid_adapters", lambda self, adapters: adapters),
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_analytics_base_query_runner.ensure_precomputed",
                return_value=ready,
            ),
        ):
            result = runner._build_costs_from_precompute(date_range)

        assert result is not None, "one unmaterializable source must not force every source back to S3"
        hogql = result.to_hogql()
        assert "marketing_costs_preaggregated" in hogql, "materialized source should read the native table"
        assert "live_s3_marker" in hogql, "unmaterializable source should stay on the live S3 union"
