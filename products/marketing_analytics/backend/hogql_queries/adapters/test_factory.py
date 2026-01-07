import pytest
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory


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

        with pytest.raises(ValidationError) as cm:
            self.config.custom_source_mappings = {
                "GoogleAds": ["partner_a", "partner_a", "partner_b"],
            }

        assert "appears multiple times" in str(cm.value)

    def test_get_all_source_identifier_mappings_integration_without_source_mapping(self):
        """Test that integrations without get_source_identifier_mapping are handled"""
        self.config.custom_source_mappings = {
            "BigQuery": ["custom_source"],
        }
        self.config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(team_config=self.config)

        assert "custom_source" not in str(mappings)
