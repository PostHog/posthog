from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.marketing_analytics.backend.services.attribution_health import (
    HOGQL_GROUP_LIMIT,
    _suggest_integration_by_alias_token,
    _UtmRow,
    get_attribution_health,
)
from products.marketing_analytics.backend.services.native_integrations import NATIVE_TO_KEY, build_combined_alias_map

_ALIAS_MAP = build_combined_alias_map({})
_ALL_TARGETS = set(NATIVE_TO_KEY.values())


class TestSuggestIntegrationByAliasToken:
    @parameterized.expand(
        [
            ("no_token_match", "zzzzzz"),
            ("empty_string", ""),
            ("typo_is_not_a_token", "fcebook"),
        ]
    )
    def test_returns_none(self, _name, raw):
        assert _suggest_integration_by_alias_token(raw, _ALIAS_MAP, _ALL_TARGETS) is None

    def test_token_matches_a_known_alias(self):
        alias, integration = next(iter(_ALIAS_MAP.items()))
        assert _suggest_integration_by_alias_token(f"{alias}_paid", _ALIAS_MAP, _ALL_TARGETS) == integration

    def test_respects_allowed_scope(self):
        alias, integration = next(iter(_ALIAS_MAP.items()))
        allowed_without = _ALL_TARGETS - {integration}
        assert _suggest_integration_by_alias_token(f"{alias}_paid", _ALIAS_MAP, allowed_without) is None


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
    async def test_token_variant_classified_as_likely_yours(self):
        self.mock_fetch.return_value = [
            _UtmRow(raw_utm_source="facebook_paid", event_count=50, last_seen_at=None),
        ]

        response = await get_attribution_health(self.team)

        meta = next(e for e in response.integrations if e.integration_key == "meta_ads")
        assert meta.events_matched_last_7d == 0
        assert meta.events_unmatched_likely_yours_last_7d == 50
        assert response.total_events_unmatched == 50
        assert response.sample_globally_unmatched
        first_sample = response.sample_globally_unmatched[0]
        assert first_sample.raw_value == "facebook_paid"
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


def _pageview(team: object, distinct_id: str, utm_source: str | None = None) -> None:
    props: dict = {}
    if utm_source is not None:
        props["utm_source"] = utm_source
    _create_event(
        distinct_id=distinct_id,
        event="$pageview",
        team=team,
        properties=props,
        timestamp=timezone.now() - timedelta(hours=1),
    )


class TestAttributionHealthKnownSourcesClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="google")
        _pageview(self.team, "u2", utm_source="google")
        _pageview(self.team, "u3", utm_source="facebook")
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_known_integration_source_counted_as_matched(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.total_events_with_utm == 3
        assert response.total_events_matched_to_any_integration == 3
        assert response.total_events_unmatched == 0

        google = next((e for e in response.integrations if e.integration_key == "google_ads"), None)
        meta = next((e for e in response.integrations if e.integration_key == "meta_ads"), None)
        assert google is not None
        assert meta is not None
        assert google.events_matched_last_7d == 2
        assert meta.events_matched_last_7d == 1


class TestAttributionHealthMisspelledSourceClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="fcebook")
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_misspelled_source_counted_as_unmatched_not_matched(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.total_events_with_utm == 1
        assert response.total_events_matched_to_any_integration == 0
        assert response.total_events_unmatched == 1
        assert len(response.sample_globally_unmatched) == 1
        assert response.sample_globally_unmatched[0].raw_value == "fcebook"


class TestAttributionHealthNoUtmClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source=None)
        _pageview(self.team, "u2", utm_source=None)
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_events_without_utm_source_not_counted(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.total_events_with_utm == 0
        assert response.total_distinct_utm_sources == 0


class TestAttributionHealthUtmNormalizationClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="  Google  ")
        _pageview(self.team, "u2", utm_source="GOOGLE")
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_hogql_trims_and_lowercases_utm_source(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.total_events_with_utm == 2
        assert response.total_events_matched_to_any_integration == 2
        raw_values = {s.raw_value for s in response.all_utm_source_samples}
        assert "google" in raw_values
        assert "  Google  " not in raw_values
        assert "GOOGLE" not in raw_values


class TestAttributionHealthMixedSourcesClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="google")
        _pageview(self.team, "u2", utm_source="fcebook")
        _pageview(self.team, "u3", utm_source="organic")
        _pageview(self.team, "u4", utm_source=None)
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_mixed_sources_total_events_correct(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.total_events_with_utm == 3
        assert response.total_distinct_utm_sources == 3
        assert response.utm_source_catalogue_truncated is False


class TestAttributionHealthCatalogueTruncatedClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        for i in range(HOGQL_GROUP_LIMIT):
            _pageview(self.team, f"u{i}", utm_source=f"unique_source_{i}")
        _pageview(self.team, "u_extra", utm_source="overflow_source")
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_utm_source_catalogue_truncated_flag_when_limit_hit(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        assert response.utm_source_catalogue_truncated is True


class TestAttributionHealthSourceTypeFilterClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="google")
        _pageview(self.team, "u2", utm_source="facebook")
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_source_type_filter_limits_integration_output(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30, source_type="GoogleAds")

        assert len(response.integrations) == 1
        assert response.integrations[0].integration_key == "google_ads"
        assert response.total_events_with_utm == 2
        assert response.total_events_matched_to_any_integration == 2
