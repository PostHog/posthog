import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.marketing_analytics.backend.services.types import (
    Campaign,
    SuggestedAction,
    TeamMappings,
    UtmAuditResponse,
    UtmIssueKind,
    UtmIssueSeverity,
)
from products.marketing_analytics.backend.services.utm_audit import (
    _build_all_utm_events,
    _build_known_sources,
    _cross_reference,
    _load_team_mappings,
    run_utm_audit,
)

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})
# known_sources set populated from every integration's default utm_source values.
# Built lazily inside tests via _build_known_sources() so we don't hardcode every value.
DEFAULT_KNOWN_SOURCES: set[str] = _build_known_sources(NO_MAPPINGS)


class TestCrossReference:
    def test_campaign_with_matching_utm_events(self):
        campaigns = [Campaign("Spring Sale", "123", "google", 100.0, 50, 1000)]
        utm_events = {("spring sale", "google"): 42}

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 42
        assert len(results[0].issues) == 0

    def test_campaign_with_no_utm_events(self):
        campaigns = [Campaign("Summer Promo", "456", "google", 500.0, 100, 5000)]

        results = _cross_reference(campaigns, {}, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results) == 1
        assert results[0].has_utm_events is False
        assert results[0].event_count == 0
        assert len(results[0].issues) == 1
        assert results[0].issues[0].field == "utm_campaign"
        assert results[0].issues[0].severity == UtmIssueSeverity.ERROR

    def test_campaign_with_source_mismatch(self):
        campaigns = [Campaign("Brand Campaign", "789", "google", 200.0, 80, 2000)]
        utm_events = {("brand campaign", "adwords"): 30}

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results) == 1
        assert results[0].has_utm_events is False
        assert len(results[0].issues) == 1
        assert results[0].issues[0].field == "utm_source"
        assert results[0].issues[0].severity == UtmIssueSeverity.WARNING

    def test_case_insensitive_matching(self):
        campaigns = [Campaign("WINTER Sale", "101", "Google", 150.0, 60, 1500)]
        utm_events = {("winter sale", "google"): 25}

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 25
        assert len(results[0].issues) == 0

    def test_multiple_campaigns_mixed_issues(self):
        campaigns = [
            Campaign("Good Campaign", "1", "google", 1000.0, 500, 10000),
            Campaign("Bad Campaign", "2", "meta", 200.0, 50, 2000),
            Campaign("Worse Campaign", "3", "google", 800.0, 100, 5000),
        ]
        utm_events = {("good campaign", "google"): 100}

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results) == 3

        good = next(r for r in results if r.campaign_name == "Good Campaign")
        bad = next(r for r in results if r.campaign_name == "Bad Campaign")
        worse = next(r for r in results if r.campaign_name == "Worse Campaign")

        assert len(good.issues) == 0
        assert good.has_utm_events is True

        assert len(bad.issues) == 1
        assert bad.issues[0].severity == UtmIssueSeverity.ERROR

        assert len(worse.issues) == 1
        assert worse.issues[0].severity == UtmIssueSeverity.ERROR

    def test_empty_campaigns(self):
        results = _cross_reference([], {}, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)
        assert len(results) == 0

    def test_custom_source_mapping_resolves_match(self):
        campaigns = [Campaign("brand_campaign", "1", "google", 500.0, 100, 5000)]
        utm_events = {("brand_campaign", "partner_blog"): 55}
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "google"},
            campaign_aliases={},
            field_preferences={},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 55
        assert len(results[0].issues) == 0

    def test_campaign_name_mapping_resolves_match(self):
        campaigns = [Campaign("brand_campaign", "1", "google", 500.0, 100, 5000)]
        utm_events = {("partner_q1", "google"): 30}
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={"brand_campaign": {"partner_q1"}},
            field_preferences={},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 30
        assert len(results[0].issues) == 0

    def test_both_mappings_together(self):
        campaigns = [Campaign("brand_campaign", "1", "google", 500.0, 100, 5000)]
        utm_events = {("partner_q1", "partner_blog"): 55}
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "google"},
            campaign_aliases={"brand_campaign": {"partner_q1"}},
            field_preferences={},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 55
        assert len(results[0].issues) == 0


class TestCrossReferenceIssueKinds:
    """Covers the 5 audit scenarios: OK / NOT_LINKED / NAME_COLLISION / NO_TAGGED_EVENTS / UNKNOWN_SOURCE."""

    def test_ok_emits_no_issue(self):
        campaigns = [Campaign("Spring Sale", "1", "google", 100.0, 50, 1000)]
        utm_events = {("spring sale", "google"): 42}

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results[0].issues) == 0

    def test_not_linked_when_no_events_match_and_no_shared_name(self):
        campaigns = [Campaign("Summer Promo", "456", "google", 500.0, 100, 5000)]

        results = _cross_reference(campaigns, {}, NO_MAPPINGS, DEFAULT_KNOWN_SOURCES)

        assert len(results[0].issues) == 1
        issue = results[0].issues[0]
        assert issue.kind == UtmIssueKind.NOT_LINKED
        assert issue.severity == UtmIssueSeverity.ERROR
        assert issue.alternative_sources == []
        assert issue.shared_with_integrations == []
        assert issue.suggested_actions == [SuggestedAction.FIX_PLATFORM_URLS]

    def test_no_tagged_events_when_alt_source_is_another_default(self):
        # Bing campaign but events only arrive with utm_source=google (Google's default).
        # Mapping google→bing would break Google attribution, so ADD_SOURCE_MAPPING must not be suggested.
        campaigns = [Campaign("Shared Campaign", "1", "bing", 100.0, 50, 1000)]
        utm_events = {("shared campaign", "google"): 29}
        known_sources = _build_known_sources(NO_MAPPINGS)

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, known_sources)

        issue = results[0].issues[0]
        assert issue.kind == UtmIssueKind.NO_TAGGED_EVENTS
        assert issue.severity == UtmIssueSeverity.WARNING
        assert issue.suggested_actions == [SuggestedAction.FIX_PLATFORM_URLS]
        assert SuggestedAction.ADD_SOURCE_MAPPING not in issue.suggested_actions
        assert len(issue.alternative_sources) == 1
        assert issue.alternative_sources[0].utm_source == "google"
        assert issue.alternative_sources[0].event_count == 29

    def test_unknown_source_when_alt_source_is_not_claimed_by_any_integration(self):
        # utm_source='partner_xyz' is not a default of any integration. Safe to offer ADD_SOURCE_MAPPING.
        campaigns = [Campaign("Brand Campaign", "1", "bing", 100.0, 50, 1000)]
        utm_events = {("brand campaign", "partner_xyz"): 40}
        known_sources = _build_known_sources(NO_MAPPINGS)
        assert "partner_xyz" not in known_sources

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, known_sources)

        issue = results[0].issues[0]
        assert issue.kind == UtmIssueKind.UNKNOWN_SOURCE
        assert issue.severity == UtmIssueSeverity.WARNING
        # Platform fix should always be listed first as the primary recommendation.
        assert issue.suggested_actions == [SuggestedAction.FIX_PLATFORM_URLS, SuggestedAction.ADD_SOURCE_MAPPING]
        assert len(issue.alternative_sources) == 1
        assert issue.alternative_sources[0].utm_source == "partner_xyz"

    def test_name_collision_when_another_platform_matches_same_name(self):
        # Both Bing and Google have "Survey". Events only tag google.
        # Google's row passes; Bing's row should be NAME_COLLISION with SWITCH_TO_ID_MATCH as primary fix.
        campaigns = [
            Campaign("Survey", "1", "bing", 100.0, 50, 1000),
            Campaign("Survey", "2", "google", 200.0, 100, 2000),
        ]
        utm_events = {("survey", "google"): 29}
        known_sources = _build_known_sources(NO_MAPPINGS)

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, known_sources)
        google = next(r for r in results if r.source_name == "google")
        bing = next(r for r in results if r.source_name == "bing")

        assert google.has_utm_events is True
        assert len(google.issues) == 0

        assert bing.has_utm_events is False
        assert len(bing.issues) == 1
        issue = bing.issues[0]
        assert issue.kind == UtmIssueKind.NAME_COLLISION
        assert issue.severity == UtmIssueSeverity.WARNING
        assert SuggestedAction.ADD_SOURCE_MAPPING not in issue.suggested_actions
        assert issue.suggested_actions[0] == SuggestedAction.SWITCH_TO_ID_MATCH
        assert issue.shared_with_integrations == ["google"]

    def test_name_collision_takes_precedence_over_unknown_source(self):
        # Even if alt_source is unknown, a shared name with another matching platform
        # should be classified as NAME_COLLISION (events likely belong to the other platform).
        campaigns = [
            Campaign("Survey", "1", "bing", 100.0, 50, 1000),
            Campaign("Survey", "2", "google", 200.0, 100, 2000),
        ]
        utm_events = {
            ("survey", "google"): 29,  # Matches google's row
            ("survey", "weird_source"): 5,  # Unknown alt for bing
        }
        known_sources = _build_known_sources(NO_MAPPINGS)

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, known_sources)
        bing = next(r for r in results if r.source_name == "bing")

        assert bing.issues[0].kind == UtmIssueKind.NAME_COLLISION
        assert "google" in bing.issues[0].shared_with_integrations

    def test_alternative_sources_sorted_by_event_count_desc(self):
        campaigns = [Campaign("Brand", "1", "bing", 100.0, 50, 1000)]
        utm_events = {
            ("brand", "partner_xyz"): 5,
            ("brand", "unknown_partner"): 30,
            ("brand", "yet_another"): 15,
        }
        known_sources = _build_known_sources(NO_MAPPINGS)

        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, known_sources)
        issue = results[0].issues[0]

        counts = [alt.event_count for alt in issue.alternative_sources]
        assert counts == sorted(counts, reverse=True)

    def test_custom_mapping_makes_source_known_blocking_suggestion(self):
        # If team already mapped 'weird_source' to google, and bing's events arrive as 'weird_source',
        # we should NOT suggest a new mapping (would conflict with the existing one).
        campaigns = [Campaign("Brand", "1", "bing", 100.0, 50, 1000)]
        utm_events = {("brand", "weird_source"): 10}
        mappings = TeamMappings(
            source_to_integration={"weird_source": "google"},
            campaign_aliases={},
            field_preferences={},
        )
        known_sources = _build_known_sources(mappings)
        assert "weird_source" in known_sources

        results = _cross_reference(campaigns, utm_events, mappings, known_sources)
        issue = results[0].issues[0]

        assert issue.kind == UtmIssueKind.NO_TAGGED_EVENTS
        assert SuggestedAction.ADD_SOURCE_MAPPING not in issue.suggested_actions


class TestBuildKnownSources:
    @pytest.mark.parametrize(
        "source,expected_present",
        [
            # Sanity-check a few well-known defaults from each integration
            ("google", True),
            ("bing", True),
            ("linkedin", True),
            ("partner_xyz", False),
            ("completely_made_up", False),
        ],
    )
    def test_membership_for_default_known_sources(self, source, expected_present):
        result = _build_known_sources(NO_MAPPINGS)

        assert (source in result) is expected_present

    def test_includes_custom_team_mappings(self):
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "google", "internal_source": "meta"},
            campaign_aliases={},
            field_preferences={},
        )

        result = _build_known_sources(mappings)

        assert "partner_blog" in result
        assert "internal_source" in result


class TestCrossReferenceFieldPreferences:
    @pytest.mark.parametrize(
        "match_field,utm_value,should_match",
        [
            ("campaign_id", "abc123", True),
            ("campaign_id", "brand campaign", False),
            ("campaign_name", "brand campaign", True),
            ("campaign_name", "abc123", False),
        ],
    )
    def test_field_preference_matching(self, match_field, utm_value, should_match):
        campaigns = [Campaign("Brand Campaign", "abc123", "google", 500.0, 100, 5000)]
        utm_events = {(utm_value, "google"): 42}
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={},
            field_preferences={"google": match_field},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 1
        if should_match:
            assert results[0].has_utm_events is True
            assert results[0].event_count == 42
            assert len(results[0].issues) == 0
        else:
            assert results[0].has_utm_events is False
            assert len(results[0].issues) == 1

    def test_mixed_preferences_per_source(self):
        campaigns = [
            Campaign("Google Brand", "g123", "google", 500.0, 100, 5000),
            Campaign("Meta Brand", "m456", "meta", 300.0, 80, 3000),
        ]
        utm_events = {
            ("g123", "google"): 30,
            ("meta brand", "meta"): 20,
        }
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={},
            field_preferences={"google": "campaign_id", "meta": "campaign_name"},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 2
        google = next(r for r in results if r.source_name == "google")
        meta = next(r for r in results if r.source_name == "meta")

        assert google.has_utm_events is True
        assert google.event_count == 30

        assert meta.has_utm_events is True
        assert meta.event_count == 20

    def test_campaign_id_with_aliases_fallback(self):
        campaigns = [Campaign("brand_campaign", "abc123", "google", 500.0, 100, 5000)]
        utm_events = {("partner_q1", "google"): 30}
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={"brand_campaign": {"partner_q1"}},
            field_preferences={"google": "campaign_id"},
        )

        results = _cross_reference(campaigns, utm_events, mappings, _build_known_sources(mappings))

        assert len(results) == 1
        assert results[0].has_utm_events is True
        assert results[0].event_count == 30


class TestBuildAllUtmEvents:
    def test_auto_matched(self):
        campaigns = [Campaign("brand", "1", "google", 0, 0, 0)]
        utm_events = {("brand", "google"): 100}

        result = _build_all_utm_events(campaigns, utm_events, NO_MAPPINGS)

        assert len(result) == 1
        assert result[0].campaign_match == "auto"
        assert result[0].source_match == "auto"
        assert result[0].matched_campaign == "brand"

    def test_fully_unmatched(self):
        campaigns = [Campaign("brand", "1", "google", 0, 0, 0)]
        utm_events = {("unknown", "facebook"): 50}

        result = _build_all_utm_events(campaigns, utm_events, NO_MAPPINGS)

        assert len(result) == 1
        assert result[0].campaign_match == "none"
        assert result[0].source_match == "none"
        assert result[0].matched_campaign is None

    def test_campaign_auto_source_none(self):
        campaigns = [Campaign("brand", "1", "google", 0, 0, 0)]
        utm_events = {("brand", "adwords"): 30}

        result = _build_all_utm_events(campaigns, utm_events, NO_MAPPINGS)

        assert len(result) == 1
        assert result[0].campaign_match == "auto"
        assert result[0].source_match == "none"
        assert result[0].matched_campaign == "brand"

    def test_source_auto_campaign_none(self):
        campaigns = [Campaign("brand", "1", "google", 0, 0, 0)]
        utm_events = {("unknown_campaign", "google"): 30}

        result = _build_all_utm_events(campaigns, utm_events, NO_MAPPINGS)

        assert len(result) == 1
        assert result[0].campaign_match == "none"
        assert result[0].source_match == "auto"
        assert result[0].matched_campaign is None

    def test_mapped_campaign_and_source(self):
        campaigns = [Campaign("brand_campaign", "1", "google", 0, 0, 0)]
        utm_events = {("partner_q1", "partner_blog"): 55}
        mappings = TeamMappings(
            source_to_integration={"partner_blog": "google"},
            campaign_aliases={"brand_campaign": {"partner_q1"}},
            field_preferences={},
        )

        result = _build_all_utm_events(campaigns, utm_events, mappings)

        assert len(result) == 1
        assert result[0].campaign_match == "mapped"
        assert result[0].source_match == "mapped"
        assert result[0].matched_campaign == "brand_campaign"

    def test_field_preference_affects_matching(self):
        campaigns = [Campaign("Brand Campaign", "abc123", "google", 0, 0, 0)]
        utm_events = {("abc123", "google"): 30}
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={},
            field_preferences={"google": "campaign_id"},
        )

        result = _build_all_utm_events(campaigns, utm_events, mappings)

        assert len(result) == 1
        assert result[0].campaign_match == "auto"
        assert result[0].source_match == "auto"
        assert result[0].matched_campaign == "Brand Campaign"

    def test_sorted_unmatched_first(self):
        campaigns = [Campaign("brand", "1", "google", 0, 0, 0)]
        utm_events = {
            ("brand", "google"): 10,
            ("orphan_a", "meta"): 50,
            ("orphan_b", "meta"): 100,
        }

        result = _build_all_utm_events(campaigns, utm_events, NO_MAPPINGS)

        assert len(result) == 3
        # Fully unmatched first (sorted by event_count desc)
        assert result[0].campaign_match == "none"
        assert result[0].event_count == 100
        assert result[1].campaign_match == "none"
        assert result[1].event_count == 50
        # Fully matched last
        assert result[2].campaign_match == "auto"
        assert result[2].source_match == "auto"


class TestLoadTeamMappings(BaseTest):
    def test_returns_empty_mappings_when_config_is_none(self):
        team = MagicMock()
        team.marketing_analytics_config = None

        result = _load_team_mappings(team)

        assert result.source_to_integration == {}
        assert result.campaign_aliases == {}
        assert result.field_preferences == {}

    def test_returns_empty_mappings_when_all_config_dicts_are_empty(self):
        self.team.marketing_analytics_config.custom_source_mappings = {}
        self.team.marketing_analytics_config.campaign_name_mappings = {}
        self.team.marketing_analytics_config.campaign_field_preferences = {}
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert result.source_to_integration == {}
        assert result.campaign_aliases == {}
        assert result.field_preferences == {}

    def test_builds_source_to_integration_from_custom_source_mappings(self):
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["partner_blog", "affiliate_site"],
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert result.source_to_integration["partner_blog"] == "google"
        assert result.source_to_integration["affiliate_site"] == "google"

    def test_normalises_custom_source_keys_to_lowercase(self):
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["UPPERCASE_SOURCE", "MixedCase"],
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert "uppercase_source" in result.source_to_integration
        assert "mixedcase" in result.source_to_integration

    def test_builds_campaign_aliases_from_campaign_name_mappings(self):
        self.team.marketing_analytics_config.campaign_name_mappings = {
            "GoogleAds": {
                "brand_campaign": ["partner_q1", "brand_q1"],
            }
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert "partner_q1" in result.campaign_aliases["brand_campaign"]
        assert "brand_q1" in result.campaign_aliases["brand_campaign"]

    def test_merges_campaign_aliases_across_multiple_integrations(self):
        self.team.marketing_analytics_config.campaign_name_mappings = {
            "GoogleAds": {"brand_campaign": ["google_alias"]},
            "MetaAds": {"brand_campaign": ["meta_alias"]},
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert "google_alias" in result.campaign_aliases["brand_campaign"]
        assert "meta_alias" in result.campaign_aliases["brand_campaign"]

    def test_normalises_campaign_alias_keys_to_lowercase(self):
        self.team.marketing_analytics_config.campaign_name_mappings = {"GoogleAds": {"Brand Campaign": ["SomeAlias"]}}
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert "brand campaign" in result.campaign_aliases
        assert "somealias" in result.campaign_aliases["brand campaign"]

    def test_builds_field_preferences_for_valid_native_source(self):
        self.team.marketing_analytics_config.campaign_field_preferences = {
            "GoogleAds": {"match_field": "campaign_id"},
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert result.field_preferences.get("google") == "campaign_id"

    def test_builds_field_preferences_for_multiple_sources(self):
        self.team.marketing_analytics_config.campaign_field_preferences = {
            "GoogleAds": {"match_field": "campaign_id"},
            "MetaAds": {"match_field": "campaign_name"},
        }
        self.team.marketing_analytics_config.save()

        result = _load_team_mappings(self.team)

        assert result.field_preferences.get("google") == "campaign_id"
        assert result.field_preferences.get("meta") == "campaign_name"

    def test_ignores_field_preferences_for_unknown_integration_type(self):
        config = MagicMock()
        config.custom_source_mappings = {}
        config.campaign_name_mappings = {}
        config.campaign_field_preferences = {"UnknownIntegration": {"match_field": "campaign_id"}}

        team = MagicMock()
        team.marketing_analytics_config = config

        result = _load_team_mappings(team)

        assert result.field_preferences == {}

    @parameterized.expand(
        [
            ("google_ads", "GoogleAds", "google"),
            ("meta_ads", "MetaAds", "meta"),
            ("linkedin_ads", "LinkedinAds", "linkedin"),
            ("tiktok_ads", "TikTokAds", "tiktok"),
            ("reddit_ads", "RedditAds", "reddit"),
            ("bing_ads", "BingAds", "bing"),
            ("snapchat_ads", "SnapchatAds", "snapchat"),
            ("pinterest_ads", "PinterestAds", "pinterest"),
        ]
    )
    def test_resolves_primary_source_for_all_native_integrations(
        self, _name, integration_type, expected_primary_source
    ):
        config = MagicMock()
        config.custom_source_mappings = {integration_type: ["custom_source"]}
        config.campaign_name_mappings = {}
        config.campaign_field_preferences = {}

        team = MagicMock()
        team.marketing_analytics_config = config

        result = _load_team_mappings(team)

        assert result.source_to_integration.get("custom_source") == expected_primary_source


class TestRunUtmAudit(BaseTest):
    def _make_campaign(
        self,
        campaign_name: str = "Spring Sale",
        campaign_id: str = "123",
        source_name: str = "google",
        spend: float = 500.0,
        clicks: int = 100,
        impressions: int = 5000,
    ) -> Campaign:
        return Campaign(
            campaign_name=campaign_name,
            campaign_id=campaign_id,
            source_name=source_name,
            spend=spend,
            clicks=clicks,
            impressions=impressions,
        )

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_returns_utm_audit_response_dataclass(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = []
        mock_utm.return_value = {}

        result = run_utm_audit(self.team)

        assert isinstance(result, UtmAuditResponse)

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_returns_zeroed_summary_when_no_campaigns(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = []
        mock_utm.return_value = {}

        result = run_utm_audit(self.team)

        assert result.total_campaigns == 0
        assert result.campaigns_with_issues == 0
        assert result.campaigns_without_issues == 0
        assert result.total_spend_at_risk == 0.0
        assert result.results == []
        assert result.all_utm_events == []

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_counts_campaigns_with_and_without_issues(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = [
            self._make_campaign("good_campaign", "1", "google", spend=100.0),
            self._make_campaign("bad_campaign", "2", "meta", spend=200.0),
        ]
        mock_utm.return_value = {("good_campaign", "google"): 50}

        result = run_utm_audit(self.team)

        assert result.total_campaigns == 2
        assert result.campaigns_with_issues == 1
        assert result.campaigns_without_issues == 1

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_sums_spend_at_risk_for_campaigns_with_issues(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = [
            self._make_campaign("no_tracking", "1", "google", spend=300.0),
            self._make_campaign("also_missing", "2", "meta", spend=150.0),
            self._make_campaign("tracked", "3", "google", spend=500.0),
        ]
        mock_utm.return_value = {("tracked", "google"): 99}

        result = run_utm_audit(self.team)

        assert result.total_spend_at_risk == pytest.approx(450.0)

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_results_sorted_by_issue_count_then_spend_descending(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = [
            self._make_campaign("low_spend_bad", "1", "google", spend=50.0),
            self._make_campaign("high_spend_bad", "2", "meta", spend=900.0),
            self._make_campaign("good", "3", "google", spend=200.0),
        ]
        mock_utm.return_value = {("good", "google"): 10}

        result = run_utm_audit(self.team)

        # Campaigns with issues come first, sorted by spend descending
        assert result.results[0].campaign_name == "high_spend_bad"
        assert result.results[1].campaign_name == "low_spend_bad"
        assert result.results[2].campaign_name == "good"

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_includes_all_utm_events_in_response(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = [self._make_campaign()]
        mock_utm.return_value = {
            ("spring sale", "google"): 100,
            ("orphan_campaign", "unknown_source"): 20,
        }

        result = run_utm_audit(self.team)

        assert len(result.all_utm_events) == 2

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_uses_team_mappings_when_resolving_sources(self, mock_campaigns, mock_utm):
        self.team.marketing_analytics_config.custom_source_mappings = {
            "GoogleAds": ["custom_blog"],
        }
        self.team.marketing_analytics_config.save()

        mock_campaigns.return_value = [self._make_campaign("spring sale", "123", "google", spend=500.0)]
        mock_utm.return_value = {("spring sale", "custom_blog"): 75}

        result = run_utm_audit(self.team)

        assert result.campaigns_with_issues == 0
        assert result.results[0].has_utm_events is True

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_passes_date_params_to_data_fetchers(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = []
        mock_utm.return_value = {}

        run_utm_audit(self.team, date_from="-7d", date_to="2024-12-31")

        mock_campaigns.assert_called_once()
        _, date_range = mock_campaigns.call_args[0]
        assert date_range.date_from_str is not None
        assert date_range.date_to_str is not None

        mock_utm.assert_called_once()
        _, utm_date_range = mock_utm.call_args[0]
        assert utm_date_range.date_from_str is not None
        assert utm_date_range.date_to_str is not None

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_zero_spend_at_risk_when_all_campaigns_tracked(self, mock_campaigns, mock_utm):
        mock_campaigns.return_value = [
            self._make_campaign("campaign_a", "1", "google", spend=200.0),
            self._make_campaign("campaign_b", "2", "meta", spend=300.0),
        ]
        mock_utm.return_value = {
            ("campaign_a", "google"): 40,
            ("campaign_b", "meta"): 60,
        }

        result = run_utm_audit(self.team)

        assert result.total_spend_at_risk == 0.0
        assert result.campaigns_with_issues == 0

    @patch("products.marketing_analytics.backend.services.utm_audit._get_utm_events")
    @patch("products.marketing_analytics.backend.services.utm_audit._get_campaigns_with_spend")
    def test_e2e_name_collision_scenario_produces_correct_kind_and_actions(self, mock_campaigns, mock_utm):
        # End-to-end smoke test: same campaign name on Bing and Google, events only tagged as google.
        # Verifies the full run_utm_audit pipeline (known_sources building, _cross_reference,
        # _build_issue) produces the expected kind and suggested_actions.
        mock_campaigns.return_value = [
            self._make_campaign("Survey", "1", "bing", spend=100.0),
            self._make_campaign("Survey", "2", "google", spend=200.0),
        ]
        mock_utm.return_value = {("survey", "google"): 29}

        result = run_utm_audit(self.team)

        bing = next(r for r in result.results if r.source_name == "bing")
        google = next(r for r in result.results if r.source_name == "google")

        assert len(google.issues) == 0
        assert len(bing.issues) == 1
        assert bing.issues[0].kind == UtmIssueKind.NAME_COLLISION
        assert bing.issues[0].suggested_actions[0] == SuggestedAction.SWITCH_TO_ID_MATCH
        assert "google" in bing.issues[0].shared_with_integrations
