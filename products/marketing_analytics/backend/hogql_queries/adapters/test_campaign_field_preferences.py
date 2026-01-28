from datetime import datetime

from posthog.test.base import BaseTest

from posthog.schema import DateRange

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.data_warehouse.backend.models import DataWarehouseTable
from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.bing_ads import BingAdsAdapter, BingAdsConfig
from products.marketing_analytics.backend.hogql_queries.adapters.google_ads import GoogleAdsAdapter, GoogleAdsConfig
from products.marketing_analytics.backend.hogql_queries.adapters.linkedin_ads import (
    LinkedinAdsAdapter,
    LinkedinAdsConfig,
)
from products.marketing_analytics.backend.hogql_queries.adapters.meta_ads import MetaAdsAdapter, MetaAdsConfig
from products.marketing_analytics.backend.hogql_queries.adapters.reddit_ads import RedditAdsAdapter, RedditAdsConfig
from products.marketing_analytics.backend.hogql_queries.adapters.tiktok_ads import TikTokAdsAdapter, TikTokAdsConfig


class TestCampaignFieldPreferences(BaseTest):
    """
    Tests for campaign field preference functionality across all adapters.
    Tests that adapters correctly respect the campaign_field_preferences configuration.
    """

    maxDiff = None

    def setUp(self):
        super().setUp()

        # Create mock data warehouse tables
        self.google_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="google_ads_campaign",
            columns={"campaign_id": "String", "campaign_name": "String"},
        )
        self.google_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="google_ads_stats",
            columns={
                "campaign_id": "String",
                "metrics_impressions": "Int64",
                "metrics_clicks": "Int64",
                "metrics_cost_micros": "Int64",
                "segments_date": "Date",
            },
        )

        self.meta_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="meta_ads_campaigns",
            columns={"id": "String", "name": "String"},
        )
        self.meta_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="meta_ads_campaign_stats",
            columns={
                "campaign_id": "String",
                "impressions": "Int64",
                "clicks": "Int64",
                "spend": "Float64",
                "date_stop": "Date",
            },
        )

        # Create query context
        self.date_range = QueryDateRange(
            date_range=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            team=self.team,
            interval=None,
            now=datetime(2024, 1, 31, 23, 59, 59),
        )
        self.context = QueryContext(
            date_range=self.date_range,
            team=self.team,
        )

    def test_googleads_always_returns_both_fields(self):
        """Test that GoogleAds adapter always returns both campaign_name and campaign_id"""
        config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="test",
            campaign_table=self.google_campaign_table,
            stats_table=self.google_stats_table,
        )
        adapter = GoogleAdsAdapter(config, self.context)

        # Build query and check both fields are returned
        query = adapter.build_query()
        assert query is not None

        # Check that campaign_name field exists
        campaign_name_expr = adapter._get_campaign_name_field()
        name_hogql = campaign_name_expr.to_hogql()
        assert "campaign_name" in name_hogql

        # Check that campaign_id field exists
        campaign_id_expr = adapter._get_campaign_id_field()
        id_hogql = campaign_id_expr.to_hogql()
        assert "campaign_id" in id_hogql

    def test_googleads_uses_campaign_id_for_matching_when_configured(self):
        """Test that GoogleAds adapter uses campaign_id for matching when configured"""
        # Configure preference for campaign_id
        self.team.marketing_analytics_config.campaign_field_preferences = {"GoogleAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="test",
            campaign_table=self.google_campaign_table,
            stats_table=self.google_stats_table,
        )
        adapter = GoogleAdsAdapter(config, self.context)

        # Check that get_campaign_match_field() returns campaign_id
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert "campaign_id" in match_hogql

        # But both fields should still be returned in the query
        campaign_name_expr = adapter._get_campaign_name_field()
        name_hogql = campaign_name_expr.to_hogql()
        assert "campaign_name" in name_hogql

    def test_metaads_always_returns_both_fields(self):
        """Test that MetaAds adapter always returns both name and id"""
        config = MetaAdsConfig(
            source_type="MetaAds",
            source_id="test",
            campaign_table=self.meta_campaign_table,
            stats_table=self.meta_stats_table,
        )
        adapter = MetaAdsAdapter(config, self.context)

        # Check that the campaign name field uses 'name' field
        campaign_name_expr = adapter._get_campaign_name_field()
        name_hogql = campaign_name_expr.to_hogql()
        assert ".name" in name_hogql

        # Check that the campaign id field uses 'id' field
        campaign_id_expr = adapter._get_campaign_id_field()
        id_hogql = campaign_id_expr.to_hogql()
        assert ".id" in id_hogql

    def test_metaads_uses_campaign_id_for_matching_when_configured(self):
        """Test that MetaAds adapter uses campaign id (field: 'id') for matching when configured"""
        # Configure preference for campaign_id
        self.team.marketing_analytics_config.campaign_field_preferences = {"MetaAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        config = MetaAdsConfig(
            source_type="MetaAds",
            source_id="test",
            campaign_table=self.meta_campaign_table,
            stats_table=self.meta_stats_table,
        )
        adapter = MetaAdsAdapter(config, self.context)

        # Check that get_campaign_match_field() uses 'id' field
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert ".id" in match_hogql

        # But both fields should still be returned
        campaign_name_expr = adapter._get_campaign_name_field()
        name_hogql = campaign_name_expr.to_hogql()
        assert ".name" in name_hogql

    def test_different_preferences_per_integration(self):
        """Test that different integrations can have different preferences simultaneously"""
        # Configure different preferences for different integrations
        self.team.marketing_analytics_config.campaign_field_preferences = {
            "GoogleAds": {"match_field": "campaign_id"},
            "MetaAds": {"match_field": "campaign_name"},
        }
        self.team.marketing_analytics_config.save()

        # GoogleAds should use campaign_id for matching
        google_config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="test",
            campaign_table=self.google_campaign_table,
            stats_table=self.google_stats_table,
        )
        google_adapter = GoogleAdsAdapter(google_config, self.context)
        google_match_field = google_adapter.get_campaign_match_field()
        google_match_hogql = google_match_field.to_hogql()
        assert "campaign_id" in google_match_hogql

        # MetaAds should use name for matching
        meta_config = MetaAdsConfig(
            source_type="MetaAds",
            source_id="test",
            campaign_table=self.meta_campaign_table,
            stats_table=self.meta_stats_table,
        )
        meta_adapter = MetaAdsAdapter(meta_config, self.context)
        meta_match_field = meta_adapter.get_campaign_match_field()
        meta_match_hogql = meta_match_field.to_hogql()
        assert ".name" in meta_match_hogql

    def test_linkedin_adapter_respects_preferences(self):
        """Test that LinkedinAds adapter respects preferences for matching"""
        linkedin_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="linkedin_ads_campaigns",
            columns={"id": "String", "name": "String"},
        )
        linkedin_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="linkedin_ads_campaign_stats",
            columns={"campaign_id": "String", "impressions": "Int64", "clicks": "Int64"},
        )

        self.team.marketing_analytics_config.campaign_field_preferences = {
            "LinkedinAds": {"match_field": "campaign_id"}
        }
        self.team.marketing_analytics_config.save()

        config = LinkedinAdsConfig(
            source_type="LinkedinAds",
            source_id="test",
            campaign_table=linkedin_campaign_table,
            stats_table=linkedin_stats_table,
        )
        adapter = LinkedinAdsAdapter(config, self.context)

        # Check that matching field uses id
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert ".id" in match_hogql

        # But name should still be available for display
        name_field_expr = adapter._get_campaign_name_field()
        name_hogql = name_field_expr.to_hogql()
        assert ".name" in name_hogql

    def test_tiktok_adapter_respects_preferences(self):
        """Test that TikTokAds adapter respects preferences for matching"""
        tiktok_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="tiktok_ads_campaigns",
            columns={"campaign_id": "String", "campaign_name": "String"},
        )
        tiktok_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="tiktok_ads_campaign_report",
            columns={"campaign_id": "String", "impressions": "Int64"},
        )

        self.team.marketing_analytics_config.campaign_field_preferences = {"TikTokAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        config = TikTokAdsConfig(
            source_type="TikTokAds",
            source_id="test",
            campaign_table=tiktok_campaign_table,
            stats_table=tiktok_stats_table,
        )
        adapter = TikTokAdsAdapter(config, self.context)

        # Check that matching field uses campaign_id
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert "campaign_id" in match_hogql

        # But name should still be available for display
        name_field_expr = adapter._get_campaign_name_field()
        name_hogql = name_field_expr.to_hogql()
        assert "campaign_name" in name_hogql

    def test_reddit_adapter_respects_preferences(self):
        """Test that RedditAds adapter respects preferences for matching"""
        reddit_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="reddit_ads_campaigns",
            columns={"id": "String", "name": "String"},
        )
        reddit_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="reddit_ads_campaign_report",
            columns={"campaign_id": "String", "impressions": "Int64"},
        )

        self.team.marketing_analytics_config.campaign_field_preferences = {"RedditAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        config = RedditAdsConfig(
            source_type="RedditAds",
            source_id="test",
            campaign_table=reddit_campaign_table,
            stats_table=reddit_stats_table,
        )
        adapter = RedditAdsAdapter(config, self.context)

        # Check that matching field uses id
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert ".id" in match_hogql

        # But name should still be available for display
        name_field_expr = adapter._get_campaign_name_field()
        name_hogql = name_field_expr.to_hogql()
        assert ".name" in name_hogql

    def test_get_campaign_field_preference_handles_missing_config(self):
        """Test that helper method handles missing team config gracefully"""
        # Explicitly clear any preferences from previous tests
        self.team.marketing_analytics_config.campaign_field_preferences = {}
        self.team.marketing_analytics_config.save()

        config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="test",
            campaign_table=self.google_campaign_table,
            stats_table=self.google_stats_table,
        )
        adapter = GoogleAdsAdapter(config, self.context)

        # Should return default
        match_field = adapter._get_campaign_field_preference()
        assert match_field == "campaign_name"

    def test_get_campaign_field_preference_handles_missing_integration_config(self):
        """Test that helper method handles missing integration-specific config gracefully"""
        # Set config for different integration
        self.team.marketing_analytics_config.campaign_field_preferences = {"MetaAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        # GoogleAds should fall back to defaults since it's not configured
        config = GoogleAdsConfig(
            source_type="GoogleAds",
            source_id="test",
            campaign_table=self.google_campaign_table,
            stats_table=self.google_stats_table,
        )
        adapter = GoogleAdsAdapter(config, self.context)

        match_field = adapter._get_campaign_field_preference()
        assert match_field == "campaign_name"

    def test_bingads_adapter_respects_preferences(self):
        """Test that BingAds adapter respects preferences for matching"""
        bing_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="bing_ads_campaigns",
            columns={"id": "String", "name": "String"},
        )
        bing_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="bing_ads_campaign_performance_report",
            columns={"campaign_id": "String", "impressions": "Int64", "clicks": "Int64", "spend": "Float64"},
        )

        self.team.marketing_analytics_config.campaign_field_preferences = {"BingAds": {"match_field": "campaign_id"}}
        self.team.marketing_analytics_config.save()

        config = BingAdsConfig(
            source_type="BingAds",
            source_id="test",
            campaign_table=bing_campaign_table,
            stats_table=bing_stats_table,
        )
        adapter = BingAdsAdapter(config, self.context)

        # Check that matching field uses id
        match_field_expr = adapter.get_campaign_match_field()
        match_hogql = match_field_expr.to_hogql()
        assert ".id" in match_hogql

        # But name should still be available for display
        name_field_expr = adapter._get_campaign_name_field()
        name_hogql = name_field_expr.to_hogql()
        assert ".name" in name_hogql

    def test_bingads_always_returns_both_fields(self):
        """Test that BingAds adapter always returns both name and id"""
        bing_campaign_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="bing_ads_campaigns_both",
            columns={"id": "String", "name": "String"},
        )
        bing_stats_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="bing_ads_campaign_performance_report_both",
            columns={"campaign_id": "String", "impressions": "Int64", "clicks": "Int64", "spend": "Float64"},
        )

        config = BingAdsConfig(
            source_type="BingAds",
            source_id="test",
            campaign_table=bing_campaign_table,
            stats_table=bing_stats_table,
        )
        adapter = BingAdsAdapter(config, self.context)

        # Build query and check both fields are returned
        query = adapter.build_query()
        assert query is not None

        # Check that the campaign name field uses 'name' field
        campaign_name_expr = adapter._get_campaign_name_field()
        name_hogql = campaign_name_expr.to_hogql()
        assert ".name" in name_hogql

        # Check that the campaign id field uses 'id' field
        campaign_id_expr = adapter._get_campaign_id_field()
        id_hogql = campaign_id_expr.to_hogql()
        assert ".id" in id_hogql
