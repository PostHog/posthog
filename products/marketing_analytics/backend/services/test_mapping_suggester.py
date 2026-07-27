import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from products.marketing_analytics.backend.services.attribution_health import (
    AttributionHealthEntry,
    AttributionHealthResponse,
    UnmatchedUtmSample,
)
from products.marketing_analytics.backend.services.mapping_suggester import suggest_utm_mappings
from products.marketing_analytics.backend.services.native_integrations import NativeIntegration


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
    async def test_v1_does_not_emit_campaign_suggestions(self):
        response = await suggest_utm_mappings(self.team)
        assert response.campaign_suggestions == []
        assert any("Campaign clustering" in n for n in response.notes)

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
