from posthog.test.base import BaseTest

from posthog.schema import BaseMathType, ConversionGoalFilter1, NodeKind

from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.conversion_goal_processor import ConversionGoalProcessor
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_config import MarketingAnalyticsConfig


class TestCustomSourceMappingsIntegration(BaseTest):
    """
    Integration tests for custom source mapping functionality.

    Tests the end-to-end flow:
    1. Team config defines custom_source_mappings
    2. Factory merges custom sources with adapter defaults
    3. ConversionGoalProcessor uses merged mappings for source normalization
    """

    maxDiff = None

    def setUp(self):
        super().setUp()
        self.config = MarketingAnalyticsConfig.from_team(self.team)

    def _create_conversion_goal(self) -> ConversionGoalFilter1:
        """Create a test conversion goal"""
        return ConversionGoalFilter1(
            kind=NodeKind.EVENTS_NODE,
            event="purchase",
            conversion_goal_id="test_goal",
            conversion_goal_name="Test Purchase Goal",
            math=BaseMathType.TOTAL,
            schema_map={"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"},
        )

    def test_processor_uses_custom_source_mappings_from_team_config(self):
        """Test that ConversionGoalProcessor uses custom_source_mappings from team config"""
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["partner_a", "custom_source_1"],
            "MetaAds": ["influencer_x"],
        }
        self.team.marketing_analytics_config.save()

        conversion_goal = self._create_conversion_goal()
        ConversionGoalProcessor(
            goal=conversion_goal, index=0, team=self.team, config=MarketingAnalyticsConfig.from_team(self.team)
        )

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )

        assert "google" in mappings
        assert "partner_a" in mappings["google"]
        assert "custom_source_1" in mappings["google"]
        assert "youtube" in mappings["google"]

        primary_meta_key = "meta" if "meta" in mappings else "facebook"
        assert "influencer_x" in mappings[primary_meta_key]

    def test_processor_normalization_includes_custom_sources(self):
        """Test that _normalize_source_field includes custom sources in normalization"""
        self.team.marketing_analytics_config.custom_source_mappings = {"GoogleAds": ["partner_a"]}
        self.team.marketing_analytics_config.save()

        conversion_goal = self._create_conversion_goal()
        ConversionGoalProcessor(
            goal=conversion_goal, index=0, team=self.team, config=MarketingAnalyticsConfig.from_team(self.team)
        )

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )

        assert "partner_a" in mappings["google"]

    def test_processor_with_empty_custom_source_mappings(self):
        """Test that processor works correctly with empty custom_source_mappings"""
        self.team.marketing_analytics_config.custom_source_mappings = {}
        self.team.marketing_analytics_config.save()

        conversion_goal = self._create_conversion_goal()
        ConversionGoalProcessor(
            goal=conversion_goal, index=0, team=self.team, config=MarketingAnalyticsConfig.from_team(self.team)
        )

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )

        assert "google" in mappings
        assert "youtube" in mappings["google"]

    def test_processor_with_multiple_custom_sources_per_integration(self):
        """Test processor with multiple custom sources for a single integration"""
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["partner_a", "partner_b", "partner_c", "custom_1", "custom_2"]
        }
        self.team.marketing_analytics_config.save()

        conversion_goal = self._create_conversion_goal()
        ConversionGoalProcessor(
            goal=conversion_goal, index=0, team=self.team, config=MarketingAnalyticsConfig.from_team(self.team)
        )

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )

        assert "google" in mappings
        for custom_source in ["partner_a", "partner_b", "partner_c", "custom_1", "custom_2"]:
            assert custom_source in mappings["google"]

    def test_factory_get_all_source_identifier_mappings_integration(self):
        """Test that factory correctly merges team config custom sources"""
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["partner_a", "partner_b"],
            "MetaAds": ["influencer_x"],
        }
        self.team.marketing_analytics_config.save()

        mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )

        assert "google" in mappings
        assert "partner_a" in mappings["google"]
        assert "partner_b" in mappings["google"]
        assert "youtube" in mappings["google"]
        assert "adwords" in mappings["google"]

        assert "meta" in mappings or "facebook" in mappings
        primary_meta_key = "meta" if "meta" in mappings else "facebook"
        assert "influencer_x" in mappings[primary_meta_key]
