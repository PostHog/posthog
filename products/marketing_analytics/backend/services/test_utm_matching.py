from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.hogql import ast

from products.marketing_analytics.backend.services.types import Campaign, MatchType, TeamMappings
from products.marketing_analytics.backend.services.utm_audit import get_campaigns_with_spend
from products.marketing_analytics.backend.services.utm_matching import (
    CampaignMatch,
    build_campaign_lookup,
    build_source_lookup,
    get_match_field,
    get_match_value,
    get_match_value_raw,
    group_campaigns_by_source,
    load_team_mappings,
    normalize_source_name,
    resolve_source,
)

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})


def _campaign(name: str, campaign_id: str, source: str, spend: float = 100.0) -> Campaign:
    return Campaign(
        campaign_name=name,
        campaign_id=campaign_id,
        source_name=source,
        spend=spend,
        clicks=0,
        impressions=0,
    )


class TestGetMatchField:
    def test_defaults_to_campaign_name(self):
        assert get_match_field("google", NO_MAPPINGS) == "campaign_name"

    def test_reads_preference_for_source(self):
        mappings = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )
        assert get_match_field("google", mappings) == "campaign_id"
        # A preference for one integration must not leak to another.
        assert get_match_field("meta", mappings) == "campaign_name"

    def test_normalizes_source_name(self):
        mappings = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )
        assert get_match_field("  Google  ", mappings) == "campaign_id"


class TestGetMatchValue:
    def test_returns_lowercased_name_by_default(self):
        assert get_match_value(_campaign("Brand_US", "12345", "google"), NO_MAPPINGS) == "brand_us"

    def test_returns_id_when_preference_is_id(self):
        mappings = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )
        assert get_match_value(_campaign("Brand_US", "12345", "google"), mappings) == "12345"


class TestResolveSource:
    def test_resolves_canonical_alias(self):
        assert resolve_source("facebook", NO_MAPPINGS) == "meta"

    def test_custom_mapping_wins_over_canonical(self):
        mappings = TeamMappings(source_to_integration={"facebook": "google"}, campaign_aliases={}, field_preferences={})
        assert resolve_source("facebook", mappings) == "google"

    def test_passes_through_unknown_value(self):
        # Callers distinguish "resolved" from "passed through" via build_known_sources.
        assert resolve_source("partner_blog", NO_MAPPINGS) == "partner_blog"


class TestBuildCampaignLookup:
    def test_maps_match_value_to_campaign_as_auto(self):
        lookup = build_campaign_lookup([_campaign("Brand_US", "1", "google")], NO_MAPPINGS)

        assert lookup == {"brand_us": CampaignMatch("Brand_US", MatchType.AUTO)}

    def test_keys_on_id_when_preference_is_id(self):
        mappings = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )

        lookup = build_campaign_lookup([_campaign("Brand_US", "12345", "google")], mappings)

        assert lookup == {"12345": CampaignMatch("Brand_US", MatchType.AUTO)}

    def test_includes_aliases_as_mapped(self):
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={"brand_us": {"brand-us-typo", "brnd_us"}},
            field_preferences={},
        )

        lookup = build_campaign_lookup([_campaign("Brand_US", "1", "google")], mappings)

        assert lookup["brand_us"].match_type == MatchType.AUTO
        assert lookup["brand-us-typo"] == CampaignMatch("Brand_US", MatchType.MAPPED)
        assert lookup["brnd_us"] == CampaignMatch("Brand_US", MatchType.MAPPED)

    def test_first_campaign_wins_on_collision(self):
        # Cross-platform name collisions are detected separately by the audit's
        # second pass — this lookup is deliberately last-write-loses.
        lookup = build_campaign_lookup(
            [_campaign("brand", "1", "google"), _campaign("brand", "2", "meta")],
            NO_MAPPINGS,
        )

        assert len(lookup) == 1
        assert lookup["brand"].match_type == MatchType.AUTO

    def test_empty_campaigns_yields_empty_lookup(self):
        assert build_campaign_lookup([], NO_MAPPINGS) == {}


class TestBuildSourceLookup:
    def test_primary_sources_are_auto(self):
        lookup = build_source_lookup([_campaign("c", "1", "google")], NO_MAPPINGS)

        assert lookup == {"google": MatchType.AUTO}

    def test_custom_mapping_to_spending_integration_is_mapped(self):
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "google"}, campaign_aliases={}, field_preferences={}
        )

        lookup = build_source_lookup([_campaign("c", "1", "google")], mappings)

        assert lookup["partner_blog"] == MatchType.MAPPED

    def test_custom_mapping_to_integration_without_spend_is_absent(self):
        # Nothing to attribute to, so the mapping must not read as "matched".
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "meta"}, campaign_aliases={}, field_preferences={}
        )

        lookup = build_source_lookup([_campaign("c", "1", "google")], mappings)

        assert "partner_blog" not in lookup


class TestLoadTeamMappings(BaseTest):
    """`self.team` is rebuilt from `setUpTestData` per test, but the config object it
    caches is not reliably reset between tests, so every test here writes the full
    config it expects rather than assuming a pristine one.
    """

    def _write_config(
        self,
        *,
        custom_source_mappings: dict | None = None,
        campaign_name_mappings: dict | None = None,
        campaign_field_preferences: dict | None = None,
    ):
        config = self.team.marketing_analytics_config
        config.custom_source_mappings = custom_source_mappings or {}
        config.campaign_name_mappings = campaign_name_mappings or {}
        config.campaign_field_preferences = campaign_field_preferences or {}
        config.save()
        return config

    def test_returns_empty_mappings_when_config_is_bare(self):
        self._write_config()

        mappings = load_team_mappings(self.team)

        assert mappings.source_to_integration == {}
        assert mappings.campaign_aliases == {}
        assert mappings.field_preferences == {}

    def test_flattens_custom_source_mappings_to_primary_source(self):
        self._write_config(custom_source_mappings={"GoogleAds": ["partner_blog", "Affiliate"]})

        mappings = load_team_mappings(self.team)

        assert mappings.source_to_integration == {"partner_blog": "google", "affiliate": "google"}

    def test_flattens_campaign_aliases_dropping_the_integration(self):
        self._write_config(campaign_name_mappings={"GoogleAds": {"Brand_US": ["brnd_us", "BRAND-US"]}})

        mappings = load_team_mappings(self.team)

        assert mappings.campaign_aliases == {"brand_us": {"brnd_us", "brand-us"}}

    def test_keys_field_preferences_by_primary_source(self):
        self._write_config(campaign_field_preferences={"GoogleAds": {"match_field": "campaign_id"}})

        mappings = load_team_mappings(self.team)

        # Keyed by 'google', not 'GoogleAds', so campaign rows can be looked up by source_name.
        assert mappings.field_preferences == {"google": "campaign_id"}

    def test_ignores_unknown_integration_types(self):
        config = self._write_config(campaign_field_preferences={"GoogleAds": {"match_field": "campaign_id"}})
        # Bypass the model validator to simulate config written by an older release.
        config._campaign_field_preferences["NotARealPlatform"] = {"match_field": "campaign_id"}

        mappings = load_team_mappings(self.team)

        assert mappings.field_preferences == {"google": "campaign_id"}


class TestCampaignsQueryShape(BaseTest):
    """Pins the column contract the campaign-field suggester depends on.

    `campaign_field_suggester` compares the utm_campaign catalogue against BOTH
    `campaign_name` and `campaign_id`, which only works because this query selects
    the two raw columns. If it were ever changed to select `match_key` instead, the
    suggester would silently compare a field to itself and always report a tie.
    """

    @patch("products.marketing_analytics.backend.services.utm_audit.execute_hogql_query")
    @patch("products.marketing_analytics.backend.services.utm_audit.MarketingSourceFactory")
    def test_selects_campaign_and_id_as_separate_raw_columns(self, mock_factory_cls, mock_execute):
        mock_factory = mock_factory_cls.return_value
        mock_factory.get_valid_adapters.return_value = [object()]
        mock_factory.build_union_query_ast.return_value = ast.SelectQuery(select=[])
        mock_execute.return_value.results = []

        get_campaigns_with_spend(self.team, self._date_range())

        query = mock_execute.call_args[0][0]
        selected_fields = [expr.chain[0] for expr in query.select if isinstance(expr, ast.Field)]
        assert selected_fields == ["campaign", "id", "source"]
        assert "match_key" not in selected_fields

    def _date_range(self):
        from django.utils import timezone

        from posthog.schema import DateRange

        from posthog.hogql_queries.utils.query_date_range import QueryDateRange

        return QueryDateRange(
            date_range=DateRange(date_from="-30d", date_to=None),
            team=self.team,
            interval=None,
            now=timezone.now(),
        )


class TestSharedMatchHelpers(BaseTest):
    """These existed as private copies in both suggesters before they moved here."""

    PREFERS_ID = TeamMappings(
        source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
    )

    def test_the_lowercased_value_is_the_raw_one_folded(self):
        # They differ only by casing; a second copy of the *field choice* is what drifts.
        campaign = _campaign("Spring_Sale_2024", "PROMO_1234", "google")

        for mappings in (NO_MAPPINGS, self.PREFERS_ID):
            assert get_match_value(campaign, mappings) == get_match_value_raw(campaign, mappings).lower()

    def test_the_raw_value_keeps_platform_casing(self):
        # What gets stored in campaign_name_mappings has to equal what the platform calls it.
        campaign = _campaign("Spring_Sale_2024", "PROMO_1234", "google")

        assert get_match_value_raw(campaign, NO_MAPPINGS) == "Spring_Sale_2024"
        assert get_match_value_raw(campaign, self.PREFERS_ID) == "PROMO_1234"

    def test_grouping_skips_campaigns_with_no_source(self):
        # A blank source would otherwise form its own "" group.
        campaigns = [
            _campaign("a", "1", "GOOGLE"),
            _campaign("b", "2", "  google  "),
            _campaign("c", "3", "   "),
        ]

        grouped = group_campaigns_by_source(campaigns)

        assert set(grouped) == {"google"}
        assert [c.campaign_name for c in grouped["google"]] == ["a", "b"]

    def test_source_names_normalize_consistently(self):
        assert normalize_source_name("  GoogleAds  ") == "googleads"
