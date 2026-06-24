from datetime import datetime
from pathlib import Path

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import override_settings

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.placeholders import replace_placeholders
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.marketing_analytics.backend.hogql_queries.adapters.base import GoogleAdsConfig, QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.google_ads import GoogleAdsAdapter

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
                now=datetime.now(),
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
