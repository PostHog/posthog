import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from products.marketing_analytics.backend.services.attribution_health import (
    AttributionHealthEntry,
    AttributionHealthResponse,
    UnmatchedUtmSample,
)
from products.marketing_analytics.backend.services.campaign_mapping_suggester import (
    CampaignMappingProposal,
    CampaignMappingSuggestions,
)
from products.marketing_analytics.backend.services.mapping_suggester import suggest_utm_mappings
from products.marketing_analytics.backend.services.native_integrations import NativeIntegration

_MODULE = "products.marketing_analytics.backend.services.mapping_suggester"


def _proposal(raw: str, clean: str, *, events: int = 100, confidence: float = 0.8) -> CampaignMappingProposal:
    return CampaignMappingProposal(
        integration="GoogleAds",
        integration_display_name="Google Ads",
        clean_name=clean,
        raw_utm_campaign=raw,
        event_count=events,
        campaign_spend=1000.0,
        score=95.0,
        confidence=confidence,
        safe_to_batch=False,
        method="fuzzy_exact_scope",
        reason=f"'{raw}' looks like a typo of '{clean}'",
        observed_utm_source="google",
        expected_utm_campaign=clean,
        expected_utm_source="google",
    )


def _sample(raw_value: str, event_count: int, suggested_integration: NativeIntegration | None) -> UnmatchedUtmSample:
    return UnmatchedUtmSample(raw_value=raw_value, event_count=event_count, suggested_integration=suggested_integration)


def _entry_with_samples(
    integration_key: NativeIntegration, samples: list[UnmatchedUtmSample]
) -> AttributionHealthEntry:
    return AttributionHealthEntry(
        integration_key=integration_key,
        display_name=integration_key,
        events_with_utm_last_7d=0,
        events_matched_last_7d=0,
        events_unmatched_likely_yours_last_7d=sum(s.event_count for s in samples),
        last_event_with_matching_utm_at=None,
        matched_pct=0.0,
        sample_unmatched_utm_sources=samples,
    )


class TestSuggestUtmMappings(APIBaseTest):
    def setUp(self):
        super().setUp()
        attribution_patcher = patch(
            "products.marketing_analytics.backend.services.mapping_suggester.get_attribution_health",
            new_callable=AsyncMock,
        )
        custom_patcher = patch(
            "products.marketing_analytics.backend.services.mapping_suggester._read_team_custom_mappings",
            new_callable=AsyncMock,
        )
        self.mock_attribution = attribution_patcher.start()
        self.mock_custom = custom_patcher.start()
        self.addCleanup(attribution_patcher.stop)
        self.addCleanup(custom_patcher.stop)

        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[],
            total_events_with_utm=0,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=0,
            sample_globally_unmatched=[],
        )
        self.mock_custom.return_value = {}

    @pytest.mark.asyncio
    async def test_campaign_suggestions_are_no_longer_hardcoded_empty(self):
        # This field returned [] unconditionally while the suggester that fills it lived beside it,
        # so every MCP consumer saw "no campaign mappings to make" no matter the data.
        proposals = CampaignMappingSuggestions(proposals=[_proposal("sprng_sale", "spring_sale")])

        response = await suggest_utm_mappings(self.team, campaign_proposals=proposals)

        assert len(response.campaign_suggestions) == 1
        suggestion = response.campaign_suggestions[0]
        assert suggestion.integration == "google_ads"  # NativeIntegration key, not the PascalCase value
        assert suggestion.suggested_clean_name == "spring_sale"
        assert suggestion.raw_campaign_values == ["sprng_sale"]
        assert suggestion.method == "fuzzy_exact_scope"

    @pytest.mark.asyncio
    async def test_proposals_for_one_target_fold_into_a_single_suggestion(self):
        # `campaign_name_mappings` stores one clean name with many raw values, so several orphans
        # pointing at the same campaign are one entry, not three.
        proposals = CampaignMappingSuggestions(
            proposals=[
                _proposal("sprng_sale", "spring_sale", events=100, confidence=0.9),
                _proposal("spring_sle", "spring_sale", events=50, confidence=0.6),
            ]
        )

        response = await suggest_utm_mappings(self.team, campaign_proposals=proposals)

        assert len(response.campaign_suggestions) == 1
        suggestion = response.campaign_suggestions[0]
        assert suggestion.raw_campaign_values == ["spring_sle", "sprng_sale"]
        assert suggestion.event_count_30d == 150
        # Applied as a unit, so it is only as trustworthy as its weakest member.
        assert suggestion.confidence == 0.6

    @pytest.mark.asyncio
    async def test_ambiguous_campaigns_are_never_offered_as_mappings(self):
        # They exist because the suggester refused to guess; this field is things to apply.
        proposals = CampaignMappingSuggestions(proposals=[], ambiguous=[object()])  # type: ignore[list-item]

        response = await suggest_utm_mappings(self.team, campaign_proposals=proposals)

        assert response.campaign_suggestions == []

    @pytest.mark.asyncio
    async def test_derives_proposals_when_the_caller_does_not_inject_them(self):
        with (
            patch(f"{_MODULE}.get_campaigns_with_spend_async", new_callable=AsyncMock) as campaigns,
            patch(f"{_MODULE}.get_utm_campaign_catalogue_async", new_callable=AsyncMock) as catalogue,
            patch(f"{_MODULE}.load_team_mappings_async", new_callable=AsyncMock),
            patch(f"{_MODULE}.suggest_campaign_name_mappings") as suggester,
        ):
            campaigns.return_value = []
            catalogue.return_value = {}
            suggester.return_value = CampaignMappingSuggestions(proposals=[_proposal("sprng", "spring")])

            response = await suggest_utm_mappings(self.team)

        assert [s.suggested_clean_name for s in response.campaign_suggestions] == ["spring"]
        campaigns.assert_awaited_once()
        catalogue.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_injected_proposals_skip_the_extra_queries(self):
        with (
            patch(f"{_MODULE}.get_campaigns_with_spend_async", new_callable=AsyncMock) as campaigns,
            patch(f"{_MODULE}.get_utm_campaign_catalogue_async", new_callable=AsyncMock) as catalogue,
        ):
            await suggest_utm_mappings(self.team, campaign_proposals=CampaignMappingSuggestions())

        campaigns.assert_not_awaited()
        catalogue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_broken_campaign_query_does_not_lose_the_source_suggestions(self):
        # campaign_suggestions going back to [] is what every consumer has today; taking the
        # source suggestions down with it would be a regression against the current behaviour.
        sample = _sample("facebook_paid", 120, "meta_ads")
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[_entry_with_samples("meta_ads", [sample])],
            total_events_with_utm=120,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=120,
            sample_globally_unmatched=[sample],
        )
        with patch(f"{_MODULE}.get_campaigns_with_spend_async", new_callable=AsyncMock) as campaigns:
            campaigns.side_effect = RuntimeError("clickhouse is having a day")

            response = await suggest_utm_mappings(self.team)

        assert response.campaign_suggestions == []
        assert [s.raw_utm_source for s in response.source_suggestions] == ["facebook_paid"]

    @pytest.mark.asyncio
    async def test_no_unmatched_returns_empty_suggestions(self):
        response = await suggest_utm_mappings(self.team)
        assert response.source_suggestions == []
        assert response.total_unmatched_events_in_window == 0

    @pytest.mark.asyncio
    async def test_token_matched_sample_becomes_suggestion(self):
        sample = _sample("facebook_paid", 120, "meta_ads")
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[_entry_with_samples("meta_ads", [sample])],
            total_events_with_utm=120,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=120,
            sample_globally_unmatched=[sample],
        )

        response = await suggest_utm_mappings(self.team)

        assert len(response.source_suggestions) == 1
        suggestion = response.source_suggestions[0]
        assert suggestion.raw_utm_source == "facebook_paid"
        assert suggestion.suggested_target == "meta_ads"
        assert suggestion.suggested_target_display_name == "Meta Ads"
        assert suggestion.event_count_30d == 120

    @pytest.mark.asyncio
    async def test_sample_without_alias_token_is_not_suggested(self):
        sample = _sample("organic", 200, None)
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[_entry_with_samples("meta_ads", [sample])],
            total_events_with_utm=200,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=200,
            sample_globally_unmatched=[sample],
        )

        response = await suggest_utm_mappings(self.team)
        assert response.source_suggestions == []
        assert any("alias" in n for n in response.notes)

    @pytest.mark.asyncio
    async def test_below_min_event_count_filtered_out(self):
        sample = _sample("facebook_paid", 3, "meta_ads")
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[_entry_with_samples("meta_ads", [sample])],
            total_events_with_utm=3,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=3,
            sample_globally_unmatched=[sample],
        )

        response = await suggest_utm_mappings(self.team, min_event_count=10)
        assert response.source_suggestions == []

    @pytest.mark.asyncio
    async def test_max_per_integration_caps_output(self):
        samples = [_sample(f"facebook_{i}", 100 - i, "meta_ads") for i in range(15)]
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[_entry_with_samples("meta_ads", samples)],
            total_events_with_utm=2000,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=2000,
            sample_globally_unmatched=samples,
        )

        response = await suggest_utm_mappings(self.team, max_per_integration=3)
        meta_count = sum(1 for s in response.source_suggestions if s.suggested_target == "meta_ads")
        assert meta_count == 3
        assert any("Meta Ads" in n and "showing top 3" in n for n in response.notes)

    @pytest.mark.asyncio
    async def test_the_note_explains_why_an_orphan_may_be_absent(self):
        # Replaces `test_v1_does_not_emit_campaign_suggestions`, which pinned the placeholder
        # behaviour: the field hardcoded to [] plus a "not yet implemented" note. Both are now
        # wrong — it is populated, and the remaining reason a campaign is missing is that the
        # suggester refused to guess between near-ties, which a consumer has to be told.
        response = await suggest_utm_mappings(self.team, campaign_proposals=CampaignMappingSuggestions())

        assert not any("not yet implemented" in n for n in response.notes)
        assert any("Near-ties are deliberately withheld" in n for n in response.notes)

    @pytest.mark.asyncio
    async def test_dedupe_when_same_raw_value_appears_in_multiple_integrations(self):
        sample_meta = _sample("paidsocial", 80, "meta_ads")
        sample_linkedin = _sample("paidsocial", 80, "linkedin_ads")
        self.mock_attribution.return_value = AttributionHealthResponse(
            lookback_days=30,
            integrations=[
                _entry_with_samples("meta_ads", [sample_meta]),
                _entry_with_samples("linkedin_ads", [sample_linkedin]),
            ],
            total_events_with_utm=80,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=80,
            sample_globally_unmatched=[sample_meta, sample_linkedin],
        )

        response = await suggest_utm_mappings(self.team)
        # The same raw value is suggested only once — the first occurrence wins.
        raw_values = [s.raw_utm_source for s in response.source_suggestions]
        assert raw_values.count("paidsocial") == 1
        assert response.source_suggestions[0].suggested_target == "meta_ads"

    @pytest.mark.asyncio
    async def test_injected_attribution_skips_the_internal_query(self):
        # The setup plan needs attribution health for its own readiness block, so it
        # hands the result in rather than paying for the aggregation twice.
        sample = _sample("facebook_paid", 120, "meta_ads")
        injected = AttributionHealthResponse(
            lookback_days=90,
            integrations=[_entry_with_samples("meta_ads", [sample])],
            total_events_with_utm=120,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=120,
            sample_globally_unmatched=[sample],
        )

        response = await suggest_utm_mappings(self.team, attribution=injected)

        self.mock_attribution.assert_not_called()
        assert [s.raw_utm_source for s in response.source_suggestions] == ["facebook_paid"]

    @pytest.mark.asyncio
    async def test_injected_attribution_window_wins_over_the_argument(self):
        # Reporting the caller's `lookback_days` would misdescribe data derived from a
        # different window, so the reported window comes off the injected response.
        injected = AttributionHealthResponse(
            lookback_days=7,
            integrations=[],
            total_events_with_utm=0,
            total_events_matched_to_any_integration=0,
            total_events_unmatched=0,
            sample_globally_unmatched=[],
        )

        response = await suggest_utm_mappings(self.team, lookback_days=365, attribution=injected)

        assert response.lookback_days_used == 7

    @pytest.mark.asyncio
    async def test_runs_its_own_query_when_attribution_is_absent(self):
        response = await suggest_utm_mappings(self.team, lookback_days=45)

        self.mock_attribution.assert_awaited_once_with(self.team, lookback_days=45)
        # Still reported off the response, which the mock pins at 30.
        assert response.lookback_days_used == 30
