from freezegun import freeze_time
from posthog.test.base import APIBaseTest

from posthog.schema import DateRange

from products.web_analytics.backend.ai_summary import (
    LIVE_RANGE_TTL,
    PAST_RANGE_TTL,
    _build_prompt,
    cache_ttl_for,
    compute_cache_key,
)
from products.web_analytics.backend.weekly_digest import DigestFilterSpec


def _spec(date_from="-7d", date_to=None, **kwargs) -> DigestFilterSpec:
    return DigestFilterSpec(date_range=DateRange(date_from=date_from, date_to=date_to), **kwargs)


def _empty_digest(extra=None) -> dict:
    digest = {
        "visitors": {"current": 100, "previous": 80, "change": {"delta": 25.0}},
        "top_pages": [],
        "top_sources": [],
        "goals": [],
        "context_events": [],
    }
    if extra:
        digest.update(extra)
    return digest


class TestBuildPrompt(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.cache_key, self.normalized = compute_cache_key(_spec(), team=self.team)

    def test_prompt_omits_context_section_when_no_events(self):
        prompt = _build_prompt(self.normalized, _empty_digest())
        assert "Recent project events" not in prompt
        assert "Filter context:" in prompt

    def test_prompt_includes_context_section_when_events_present(self):
        digest = _empty_digest(
            {
                "context_events": [
                    {
                        "kind": "annotation",
                        "name": "deployed v3.4",
                        "date": "2026-05-25T10:00:00+00:00",
                        "summary": "manual annotation",
                    },
                ]
            }
        )
        prompt = _build_prompt(self.normalized, digest)
        assert "Recent project events" in prompt
        assert "annotation" in prompt
        assert "deployed v3.4" in prompt
        assert "2026-05-25" in prompt

    def test_prompt_includes_correlation_style_rule_when_events_present(self):
        digest = _empty_digest(
            {
                "context_events": [
                    {
                        "kind": "annotation",
                        "name": "deployed v3.4",
                        "date": "2026-05-25T10:00:00+00:00",
                        "summary": "manual annotation",
                    }
                ]
            }
        )
        prompt = _build_prompt(self.normalized, digest)
        assert "coincides with" in prompt
        assert "Never assert causation" in prompt


class TestComputeCacheKey(APIBaseTest):
    def test_key_is_stable_for_same_spec(self):
        key_a, _ = compute_cache_key(_spec(), team=self.team)
        key_b, _ = compute_cache_key(_spec(), team=self.team)
        assert key_a == key_b

    def test_key_does_not_rotate_over_time(self):
        # Regression: the key must not embed the current wall-clock, or a summary cached at one hour
        # would never be found at the next, defeating the TTL.
        with freeze_time("2026-05-28 11:55:00"):
            key_early, _ = compute_cache_key(_spec(), team=self.team)
        with freeze_time("2026-05-28 12:05:00"):
            key_later, _ = compute_cache_key(_spec(), team=self.team)
        assert key_early == key_later

    def test_key_changes_with_date_range(self):
        key_7d, _ = compute_cache_key(_spec(date_from="-7d"), team=self.team)
        key_30d, _ = compute_cache_key(_spec(date_from="-30d"), team=self.team)
        assert key_7d != key_30d

    def test_key_changes_with_filter_options(self):
        key_a, _ = compute_cache_key(_spec(filter_test_accounts=True), team=self.team)
        key_b, _ = compute_cache_key(_spec(filter_test_accounts=False), team=self.team)
        assert key_a != key_b

    def test_key_is_scoped_to_team(self):
        other_team = self.organization.teams.create(name="Other team")
        key_self, _ = compute_cache_key(_spec(), team=self.team)
        key_other, _ = compute_cache_key(_spec(), team=other_team)
        assert key_self != key_other

    def test_key_independent_of_property_order(self):
        props_a = [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}]
        props_b = [{"key": "b", "value": "2"}, {"key": "a", "value": "1"}]
        key_a, _ = compute_cache_key(_spec(properties=props_a), team=self.team)
        key_b, _ = compute_cache_key(_spec(properties=props_b), team=self.team)
        assert key_a == key_b


class TestCacheTTL(APIBaseTest):
    def test_open_ended_range_is_live(self):
        with freeze_time("2026-05-28 12:00:00"):
            assert cache_ttl_for(_spec(date_from="-7d", date_to=None), team=self.team) == LIVE_RANGE_TTL

    def test_range_ending_now_is_live(self):
        with freeze_time("2026-05-28 12:00:00"):
            assert cache_ttl_for(_spec(date_from="-7d", date_to="0d"), team=self.team) == LIVE_RANGE_TTL

    def test_closed_past_range_uses_long_ttl(self):
        with freeze_time("2026-05-28 12:00:00"):
            assert cache_ttl_for(_spec(date_from="2026-01-01", date_to="2026-01-31"), team=self.team) == PAST_RANGE_TTL
