from datetime import datetime
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import Mock

from django.core.exceptions import ValidationError

from posthog.schema import DateRange, MarketingAnalyticsDrillDownLevel

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import DEFAULT_CURRENCY

from products.data_warehouse.backend.models import DataWarehouseTable
from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.meta_ads import MetaAdsAdapter


class TestMarketingSourceFactoryCustomSourceMappings(BaseTest):
    """Test suite for MarketingSourceFactory custom source mapping functionality"""

    def setUp(self):
        super().setUp()
        self.config = self.team.marketing_analytics_config

    def test_get_all_source_identifier_mappings_without_team_config(self):
        """Test that factory returns only adapter defaults when no team config provided"""
        mappings = MarketingSourceFactory.get_all_source_identifier_mappings()

        assert "google" in mappings
        assert "youtube" in mappings["google"]
        assert "adwords" in mappings["google"]
        assert "meta" in mappings or "facebook" in mappings

    def test_get_all_source_identifier_mappings_with_empty_custom_mappings(self):
        """Test that factory handles empty custom_source_mappings correctly"""
        self.config.custom_source_mappings = {}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "google" in mappings
        assert "youtube" in mappings["google"]

    def test_get_all_source_identifier_mappings_merges_custom_sources_googleads(self):
        """Test that custom sources for GoogleAds are merged with adapter defaults"""
        self.config.custom_source_mappings = {"GoogleAds": ["partner_a", "custom_source_1"]}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "google" in mappings
        assert "partner_a" in mappings["google"]
        assert "custom_source_1" in mappings["google"]

    def test_get_all_source_identifier_mappings_merges_custom_sources_metaads(self):
        """Test that custom sources for MetaAds are merged with adapter defaults"""
        self.config.custom_source_mappings = {"MetaAds": ["influencer_campaign"]}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "meta" in mappings or "facebook" in mappings
        primary_meta_key = "meta" if "meta" in mappings else "facebook"
        assert "influencer_campaign" in mappings[primary_meta_key]

    def test_get_all_source_identifier_mappings_merges_custom_sources_tiktokads(self):
        """Test that custom sources for TikTokAds are merged with adapter defaults"""
        self.config.custom_source_mappings = {"TikTokAds": ["tiktok_partner"]}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "tiktok" in mappings
        assert "tiktok_partner" in mappings["tiktok"]

    def test_get_all_source_identifier_mappings_merges_custom_sources_linkedinads(self):
        """Test that custom sources for LinkedinAds are merged with adapter defaults"""
        self.config.custom_source_mappings = {"LinkedinAds": ["linkedin_custom"]}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "linkedin" in mappings
        assert "linkedin_custom" in mappings["linkedin"]

    def test_get_all_source_identifier_mappings_preserves_adapter_defaults(self):
        """Test that custom sources don't replace adapter defaults, only extend them"""
        self.config.custom_source_mappings = {"GoogleAds": ["partner_a"]}
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "google" in mappings
        assert "youtube" in mappings["google"]
        assert "adwords" in mappings["google"]
        assert "partner_a" in mappings["google"]

    def test_get_all_source_identifier_mappings_multiple_integrations(self):
        """Test that custom sources work for multiple integrations simultaneously"""
        self.config.custom_source_mappings = {
            "GoogleAds": ["google_partner_a", "google_partner_b"],
            "MetaAds": ["meta_influencer_x"],
            "TikTokAds": ["tiktok_custom"],
        }
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "google_partner_a" in mappings["google"]
        assert "google_partner_b" in mappings["google"]
        assert "meta_influencer_x" in mappings.get("meta", mappings.get("facebook", []))
        assert "tiktok_custom" in mappings["tiktok"]

    def test_get_all_source_identifier_mappings_invalid_integration_type(self):
        """Test that invalid integration types are silently ignored"""
        self.config.custom_source_mappings = {
            "GoogleAds": ["partner_a"],
            "InvalidIntegration": ["should_be_ignored"],
        }
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "partner_a" in mappings["google"]
        assert "should_be_ignored" not in str(mappings)

    def test_get_all_source_identifier_mappings_duplicate_sources_within_integration_rejected(self):
        """Test that duplicate sources within same integration are rejected"""

        with self.assertRaises(ValidationError) as cm:
            self.config.custom_source_mappings = {
                "GoogleAds": ["partner_a", "partner_a", "partner_b"],
            }

        assert "appears multiple times" in str(cm.exception)

    def test_get_all_source_identifier_mappings_integration_without_source_mapping(self):
        """Test that integrations without get_source_identifier_mapping are handled"""
        self.config.custom_source_mappings = {
            "BigQuery": ["custom_source"],
        }
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "custom_source" not in str(mappings)


class TestMetaAdsConfigDiscovery(BaseTest):
    """Test suite for `_create_metaads_config` discovery of optional ad-group / ad tables.

    The factory must correctly populate `adset_table` / `adset_stats_table` /
    `ad_table` / `ad_stats_table` slots based on the user's synced schemas.
    Missing optional tables → those slots stay None → adapter's `supports_level`
    returns False at AD_GROUP / AD respectively.
    """

    def _make_table(self, schema_name: str) -> DataWarehouseTable:
        """Build a DataWarehouseTable mock with name `metaads_<schema_name>`. The
        factory's `_extract_schema_name` strips the `metaads_` prefix to get the
        canonical schema name, which is what we match against MetaAdsResource.
        """
        table = Mock()
        table.name = f"metaads_{schema_name}"
        return cast(DataWarehouseTable, table)

    def _make_factory(self) -> MarketingSourceFactory:
        date_range = QueryDateRange(
            date_range=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            team=self.team,
            interval=None,
            now=datetime.now(),
        )
        context = QueryContext(date_range=date_range, team=self.team, base_currency=DEFAULT_CURRENCY)
        return MarketingSourceFactory(context=context)

    def _make_source(self) -> Mock:
        source = Mock()
        source.id = "meta_source_id"
        source.source_type = "MetaAds"
        return source

    def test_meta_only_campaign_tables_yields_config_with_no_optional_tables(self):
        """Bare-minimum sync (campaigns + campaign_stats) → adapter loads but
        cannot serve AD_GROUP / AD."""
        factory = self._make_factory()
        tables = [self._make_table("campaigns"), self._make_table("campaign_stats")]

        config = factory._create_metaads_config(self._make_source(), tables)

        assert config is not None
        assert config.campaign_table.name == "metaads_campaigns"
        assert config.stats_table.name == "metaads_campaign_stats"
        assert config.adset_table is None
        assert config.adset_stats_table is None
        assert config.ad_table is None
        assert config.ad_stats_table is None

    def test_meta_with_full_hierarchy_yields_all_six_tables(self):
        """All Meta resources synced → all six slots populated → adapter supports
        every drill-down level."""
        factory = self._make_factory()
        tables = [
            self._make_table("campaigns"),
            self._make_table("campaign_stats"),
            self._make_table("adsets"),
            self._make_table("adset_stats"),
            self._make_table("ads"),
            self._make_table("ad_stats"),
        ]

        config = factory._create_metaads_config(self._make_source(), tables)

        assert config is not None
        assert config.adset_table is not None and config.adset_table.name == "metaads_adsets"
        assert config.adset_stats_table is not None and config.adset_stats_table.name == "metaads_adset_stats"
        assert config.ad_table is not None and config.ad_table.name == "metaads_ads"
        assert config.ad_stats_table is not None and config.ad_stats_table.name == "metaads_ad_stats"

    def test_meta_with_only_adset_tables_supports_ad_group_but_not_ad(self):
        """Partial hierarchy (adsets but no ads) → AD_GROUP works, AD doesn't."""
        factory = self._make_factory()
        tables = [
            self._make_table("campaigns"),
            self._make_table("campaign_stats"),
            self._make_table("adsets"),
            self._make_table("adset_stats"),
        ]

        config = factory._create_metaads_config(self._make_source(), tables)
        assert config is not None
        adapter = MetaAdsAdapter(config=config, context=factory.context)

        assert adapter.supports_level(MarketingAnalyticsDrillDownLevel.CAMPAIGN)
        assert adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD_GROUP)
        assert not adapter.supports_level(MarketingAnalyticsDrillDownLevel.AD)

    def test_meta_without_required_campaign_tables_returns_none(self):
        """Missing campaigns or campaign_stats → adapter can't load at all."""
        factory = self._make_factory()
        tables_no_stats = [self._make_table("campaigns")]
        assert factory._create_metaads_config(self._make_source(), tables_no_stats) is None

        tables_no_campaign = [self._make_table("campaign_stats")]
        assert factory._create_metaads_config(self._make_source(), tables_no_campaign) is None
