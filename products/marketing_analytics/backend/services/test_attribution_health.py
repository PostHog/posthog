from datetime import UTC, datetime

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from products.marketing_analytics.backend.services.attribution_health import (
    FUZZY_LIKELY_THRESHOLD,
    _fuzzy_best_integration,
    _UtmRow,
    get_attribution_health,
)


class TestFuzzyBestIntegration:
    def test_close_match_meta_returns_meta_with_high_ratio(self):
        target, ratio = _fuzzy_best_integration("fcebook", candidates=["meta_ads", "google_ads"])
        assert target == "meta_ads"
        assert ratio >= FUZZY_LIKELY_THRESHOLD

    def test_no_candidates_returns_none(self):
        target, ratio = _fuzzy_best_integration("anything", candidates=[])
        assert target is None
        assert ratio == 0.0

    def test_empty_string_returns_none(self):
        target, ratio = _fuzzy_best_integration("", candidates=["meta_ads"])
        assert target is None
        assert ratio == 0.0

    def test_unrelated_value_returns_low_ratio(self):
        _, ratio = _fuzzy_best_integration("zzzzzz", candidates=["meta_ads", "google_ads"])
        assert ratio < FUZZY_LIKELY_THRESHOLD


class TestGetAttributionHealth(APIBaseTest):
    def setUp(self):
        super().setUp()
        from products.marketing_analytics.backend.services.native_integrations import canonical_source_aliases

        fetch_patcher = patch(
            "products.marketing_analytics.backend.services.attribution_health._fetch_utm_groups",
            new_callable=AsyncMock,
        )
        alias_patcher = patch(
            "products.marketing_analytics.backend.services.attribution_health._build_team_alias_map",
            new_callable=AsyncMock,
        )
        self.mock_fetch = fetch_patcher.start()
        self.mock_alias = alias_patcher.start()
        self.addCleanup(fetch_patcher.stop)
        self.addCleanup(alias_patcher.stop)

        self.mock_fetch.return_value = []
        # Real canonical alias table — gives tests realistic match behavior
        # without going through the team's marketing_analytics_config.
        self.mock_alias.return_value = dict(canonical_source_aliases())

    @pytest.mark.asyncio
    async def test_no_events_returns_zeroed_response(self):
        response = await get_attribution_health(self.team)
        assert response.total_events_with_utm == 0
        assert response.total_events_matched_to_any_integration == 0
        assert response.total_events_unmatched == 0
        assert response.sample_globally_unmatched == []
        assert all(e.events_matched_last_7d == 0 for e in response.integrations)

    @pytest.mark.asyncio
    async def test_known_alias_counts_as_matched(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="facebook", event_count=120, last_seen_at=None),
            _UtmRow(raw_utm_source="adwords", event_count=80, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team)

        assert response.total_events_with_utm == 200
        assert response.total_events_matched_to_any_integration == 200
        assert response.total_events_unmatched == 0

        meta = next(e for e in response.integrations if e.integration_key == "meta_ads")
        google = next(e for e in response.integrations if e.integration_key == "google_ads")
        assert meta.events_matched_last_7d == 120
        assert google.events_matched_last_7d == 80
        assert meta.matched_pct == round(120 / 200 * 100, 2)

    @pytest.mark.asyncio
    async def test_fuzzy_value_classified_as_likely_yours(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="fcebook", event_count=50, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team)

        meta = next(e for e in response.integrations if e.integration_key == "meta_ads")
        assert meta.events_matched_last_7d == 0
        assert meta.events_unmatched_likely_yours_last_7d == 50
        assert response.total_events_unmatched == 50
        assert response.sample_globally_unmatched
        first_sample = response.sample_globally_unmatched[0]
        assert first_sample.raw_value == "fcebook"
        assert first_sample.suggested_integration == "meta_ads"

    @pytest.mark.asyncio
    async def test_completely_unrelated_value_unmatched_no_likely(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="zzz123", event_count=10, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team)

        assert response.total_events_unmatched == 10
        for entry in response.integrations:
            assert entry.events_unmatched_likely_yours_last_7d == 0

    @pytest.mark.asyncio
    async def test_filter_by_source_type_limits_output_but_not_totals(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="facebook", event_count=100, last_seen_at=None),
            _UtmRow(raw_utm_source="adwords", event_count=200, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team, source_type="GoogleAds")

        assert len(response.integrations) == 1
        assert response.integrations[0].integration_key == "google_ads"
        # Totals reflect ALL events the team had (intentional — overall context still useful).
        assert response.total_events_with_utm == 300
        assert response.total_events_matched_to_any_integration == 300

    @pytest.mark.asyncio
    async def test_unknown_source_type_filter_returns_empty(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="facebook", event_count=100, last_seen_at=None),
        ]
        response = await get_attribution_health(self.team, source_type="NotASource")
        assert response.integrations == []

    @pytest.mark.asyncio
    async def test_last_event_with_matching_utm_is_max_across_aliases(self):
        earlier = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
        later = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="facebook", event_count=10, last_seen_at=earlier),
            _UtmRow(raw_utm_source="fb", event_count=5, last_seen_at=later),
            _UtmRow(raw_utm_source="instagram", event_count=3, last_seen_at=earlier),
        ]

        response = await get_attribution_health(self.team)

        meta = next(e for e in response.integrations if e.integration_key == "meta_ads")
        assert meta.last_event_with_matching_utm_at == later
        assert meta.events_matched_last_7d == 18

    @pytest.mark.asyncio
    async def test_globally_unmatched_sorted_by_event_count(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="zzz1", event_count=5, last_seen_at=None),
            _UtmRow(raw_utm_source="zzz2", event_count=50, last_seen_at=None),
            _UtmRow(raw_utm_source="zzz3", event_count=20, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team)

        counts = [s.event_count for s in response.sample_globally_unmatched]
        assert counts == sorted(counts, reverse=True)
