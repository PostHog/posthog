from datetime import UTC, datetime, timedelta

import pytest
import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.team.team import Team

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


class TestGetAttributionHealth(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.team = Team(id=1)
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
    async def test_custom_mapping_uses_only_the_mapped_platform_paid_signals(self) -> None:
        self.mock_fetch.return_value = [
            _UtmRow(
                raw_utm_source="custom-source",
                event_count=3,
                last_seen_at=None,
                paid_event_count=1,
                platform_paid_event_counts={"openai_ads": 2, "google_ads": 3},
            ),
        ]
        response = await get_attribution_health(self.team, custom_source_mappings={"OpenAIAds": ["custom-source"]})
        openai = next(e for e in response.integrations if e.integration_key == "openai_ads")
        google = next(e for e in response.integrations if e.integration_key == "google_ads")
        assert openai.events_matched_paid_last_7d == 2
        assert google.events_matched_paid_last_7d == 0

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


def _pageview(
    team: object,
    distinct_id: str,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    gclid: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    props: dict = {}
    if utm_source is not None:
        props["utm_source"] = utm_source
    if utm_medium is not None:
        props["utm_medium"] = utm_medium
    if gclid is not None:
        props["gclid"] = gclid
    _create_event(
        distinct_id=distinct_id,
        event="$pageview",
        team=team,
        properties=props,
        timestamp=timestamp or timezone.now() - timedelta(hours=1),
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


@time_machine.travel("2026-09-15T12:00:00Z", tick=False)
class TestAttributionHealthPaidSignalClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            ("google", "google_ads", "gclid"),
            ("google", "google_ads", "gbraid"),
            ("google", "google_ads", "wbraid"),
            ("google", "google_ads", "gad_source"),
            ("google", "google_ads", "gad_campaignid"),
            ("chatgpt", "openai_ads", "oppref"),
            ("bing", "bing_ads", "msclkid"),
            ("linkedin", "linkedin_ads", "li_fat_id"),
            ("reddit", "reddit_ads", "rdt_cid"),
            ("snapchat", "snapchat_ads", "ScCid"),
            ("snapchat", "snapchat_ads", "sccid"),
            ("tiktok", "tiktok_ads", "ttclid"),
            ("rokt", "rokt_ads", "rtid"),
            ("pinterest", "pinterest_ads", "pp"),
        ]
    )
    @pytest.mark.asyncio
    async def test_platform_ad_signals_count_each_event_once(self, source: str, key: str, parameter: str) -> None:
        value = "0" if parameter == "pp" else "example-click"
        event_properties = [
            {parameter: value},
            {"$current_url": f"https://example.com/?{parameter}={value}"},
            {parameter: value, "utm_medium": "cpc"},
            {"utm_medium": " paid-social "},
            {"utm_campaign": "product-guide", "utm_medium": "referral"},
            {parameter: ""},
            {parameter: "  ", "$current_url": f"https://example.com/?{parameter}=%20"},
            {"msclkid" if key != "bing_ads" else "gclid": "other-platform-click"},
        ]
        for index, properties in enumerate(event_properties):
            _create_event(
                team=self.team,
                distinct_id=f"visitor-{index}",
                event="$pageview",
                timestamp=timezone.now() - timedelta(hours=1),
                properties={"utm_source": source, **properties},
            )
        flush_persons_and_events()

        response = await get_attribution_health(self.team, custom_source_mappings={})

        entry = next(e for e in response.integrations if e.integration_key == key)
        assert entry.events_matched_last_7d == len(event_properties)
        assert entry.events_matched_paid_last_7d == 4
        assert entry.events_matched_tagged_medium_last_7d == 3

    @parameterized.expand(
        [
            ("openai_referral", "chatgpt", "openai_ads", {"utm_campaign": "product-guide"}),
            ("chatgpt_domain_referral", "chatgpt.com", "openai_ads", {"utm_campaign": "product-guide"}, 0, 0),
            ("google_campaign", "google", "google_ads", {"utm_campaign": "spring-guide"}),
            ("meta_click", "facebook", "meta_ads", {"fbclid": "example-click"}),
            ("meta_url", "facebook", "meta_ads", {"$current_url": "https://example.com/?fbclid=example-click"}),
            ("pinterest_click", "pinterest", "pinterest_ads", {"epik": "example-click"}),
            (
                "pinterest_earned",
                "pinterest",
                "pinterest_ads",
                {"pp": "1", "utm_medium": "cpc", "epik": "example-click"},
            ),
            (
                "pinterest_earned_url",
                "pinterest",
                "pinterest_ads",
                {"utm_medium": "paid-social", "$current_url": "https://example.com/?pp=1"},
            ),
            ("snap_cookie", "snapchat", "snapchat_ads", {"_scid": "example-cookie"}),
            ("apple_campaign", "apple", "apple_ads", {"utm_campaign": "product-guide"}),
            ("amazon_campaign", "amazon", "amazon_ads", {"utm_campaign": "product-guide"}),
            ("meta_paid", "facebook", "meta_ads", {"utm_medium": "cpc"}, 1),
            ("apple_paid", "apple", "apple_ads", {"utm_medium": "cpc"}, 1),
            ("amazon_paid", "amazon", "amazon_ads", {"utm_medium": "cpc"}, 1),
        ]
    )
    @pytest.mark.asyncio
    async def test_campaigns_and_tracking_parameters_require_paid_evidence(
        self,
        _name: str,
        source: str,
        key: str,
        properties: dict[str, str],
        expected_paid: int = 0,
        expected_matched: int = 1,
    ) -> None:
        _create_event(
            team=self.team,
            distinct_id="visitor",
            event="$pageview",
            timestamp=timezone.now() - timedelta(hours=1),
            properties={"utm_source": source, **properties},
        )
        flush_persons_and_events()

        response = await get_attribution_health(self.team, custom_source_mappings={})

        entry = next(e for e in response.integrations if e.integration_key == key)
        assert entry.events_matched_last_7d == expected_matched
        assert entry.events_matched_paid_last_7d == expected_paid


@time_machine.travel("2025-06-15", tick=False)
class TestAttributionHealthFutureTimestampClickhouse(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        _pageview(self.team, "u1", utm_source="google")
        _pageview(self.team, "u2", utm_source="google", timestamp=timezone.now() + timedelta(days=1800))
        flush_persons_and_events()

    def tearDown(self) -> None:
        flush_persons_and_events()
        super().tearDown()

    @pytest.mark.asyncio
    async def test_future_stamped_event_is_excluded(self) -> None:
        response = await get_attribution_health(self.team, lookback_days=30)

        google = next(e for e in response.integrations if e.integration_key == "google_ads")
        assert google.events_matched_last_7d == 1
        assert response.total_events_with_utm == 1
        assert google.last_event_with_matching_utm_at is not None
        assert google.last_event_with_matching_utm_at <= timezone.now()
