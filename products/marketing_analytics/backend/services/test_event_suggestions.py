import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from products.marketing_analytics.backend.services.event_suggestions import (
    DEFAULT_EXCLUDED_EVENTS,
    _build_reason,
    _compute_score,
    suggest_conversion_goals,
)


class TestComputeScore:
    def test_high_volume_high_utm_not_goal_scores_near_one(self):
        score = _compute_score(count=1000, max_volume=1000, pct_utm_source=100, is_already_a_goal=False)
        assert 0.99 <= score <= 1.0

    def test_already_a_goal_loses_score_bonus(self):
        not_goal = _compute_score(count=500, max_volume=1000, pct_utm_source=80, is_already_a_goal=False)
        already = _compute_score(count=500, max_volume=1000, pct_utm_source=80, is_already_a_goal=True)
        assert not_goal > already

    def test_zero_volume_safe(self):
        score = _compute_score(count=0, max_volume=0, pct_utm_source=0, is_already_a_goal=False)
        assert 0 <= score <= 1


class TestBuildReason:
    def test_high_volume_phrasing(self):
        reason = _build_reason(count=5000, pct_utm_source=80, is_already_a_goal=False)
        assert "high volume" in reason
        assert "5,000" in reason
        assert "strong UTM" in reason
        assert "not yet a goal" in reason

    def test_low_utm_phrasing(self):
        reason = _build_reason(count=200, pct_utm_source=5, is_already_a_goal=False)
        assert "low UTM coverage" in reason

    def test_already_goal_marked(self):
        reason = _build_reason(count=200, pct_utm_source=50, is_already_a_goal=True)
        assert "already configured as a goal" in reason


class TestSuggestConversionGoals(APIBaseTest):
    def setUp(self):
        super().setUp()
        fetch_patcher = patch(
            "products.marketing_analytics.backend.services.event_suggestions._fetch_candidate_rows",
            new_callable=AsyncMock,
        )
        goals_patcher = patch(
            "products.marketing_analytics.backend.services.event_suggestions._read_existing_goal_event_names",
            new_callable=AsyncMock,
        )
        self.mock_fetch = fetch_patcher.start()
        self.mock_goals = goals_patcher.start()
        self.addCleanup(fetch_patcher.stop)
        self.addCleanup(goals_patcher.stop)

        self.mock_fetch.return_value = []
        self.mock_goals.return_value = set()

    @pytest.mark.asyncio
    async def test_no_events_returns_empty(self):
        response = await suggest_conversion_goals(self.team)
        assert response.candidates == []

    @pytest.mark.asyncio
    async def test_excludes_default_system_events(self):
        self.mock_fetch.return_value = [
            {
                "event_name": "$pageview",
                "count": 10000,
                "users": 500,
                "with_utm_source": 8000,
                "with_utm_campaign": 5000,
                "top_utm_sources": [],
            },
            {
                "event_name": "purchase",
                "count": 1000,
                "users": 100,
                "with_utm_source": 800,
                "with_utm_campaign": 600,
                "top_utm_sources": [],
            },
        ]
        response = await suggest_conversion_goals(self.team)
        assert len(response.candidates) == 1
        assert response.candidates[0].event_name == "purchase"

    @pytest.mark.asyncio
    async def test_disabling_exclusion_includes_autocapture(self):
        self.mock_fetch.return_value = [
            {
                "event_name": "$autocapture",
                "count": 10000,
                "users": 500,
                "with_utm_source": 0,
                "with_utm_campaign": 0,
                "top_utm_sources": [],
            },
        ]
        response = await suggest_conversion_goals(self.team, exclude_autocapture=False)
        assert len(response.candidates) == 1
        assert response.candidates[0].event_name == "$autocapture"

    @pytest.mark.asyncio
    async def test_already_a_goal_flag_set(self):
        self.mock_fetch.return_value = [
            {
                "event_name": "purchase",
                "count": 1000,
                "users": 100,
                "with_utm_source": 700,
                "with_utm_campaign": 500,
                "top_utm_sources": [],
            },
            {
                "event_name": "signup",
                "count": 500,
                "users": 80,
                "with_utm_source": 250,
                "with_utm_campaign": 100,
                "top_utm_sources": [],
            },
        ]
        self.mock_goals.return_value = {"purchase"}
        response = await suggest_conversion_goals(self.team)
        purchase = next(c for c in response.candidates if c.event_name == "purchase")
        signup = next(c for c in response.candidates if c.event_name == "signup")
        assert purchase.is_already_a_goal is True
        assert signup.is_already_a_goal is False
        # The not-a-goal bonus is surfaced in the reason text for each candidate.
        assert "already configured as a goal" in purchase.suggestion_reason
        assert "not yet a goal" in signup.suggestion_reason

    @pytest.mark.asyncio
    async def test_top_n_caps_results(self):
        self.mock_fetch.return_value = [
            {
                "event_name": f"event_{i}",
                "count": 1000 - i,
                "users": 50,
                "with_utm_source": 500,
                "with_utm_campaign": 200,
                "top_utm_sources": [],
            }
            for i in range(20)
        ]
        response = await suggest_conversion_goals(self.team, top_n=5)
        assert len(response.candidates) == 5

    @pytest.mark.asyncio
    async def test_candidates_sorted_by_score_descending(self):
        self.mock_fetch.return_value = [
            {
                "event_name": "low_volume",
                "count": 100,
                "users": 20,
                "with_utm_source": 80,
                "with_utm_campaign": 60,
                "top_utm_sources": [],
            },
            {
                "event_name": "high_volume",
                "count": 5000,
                "users": 500,
                "with_utm_source": 4500,
                "with_utm_campaign": 3000,
                "top_utm_sources": [],
            },
            {
                "event_name": "no_utm",
                "count": 3000,
                "users": 300,
                "with_utm_source": 0,
                "with_utm_campaign": 0,
                "top_utm_sources": [],
            },
        ]
        response = await suggest_conversion_goals(self.team)
        scores = [c.suggestion_score for c in response.candidates]
        assert scores == sorted(scores, reverse=True)
        assert response.candidates[0].event_name == "high_volume"

    @pytest.mark.asyncio
    async def test_pct_with_utm_clamped_to_count(self):
        self.mock_fetch.return_value = [
            {
                "event_name": "purchase",
                "count": 1000,
                "users": 100,
                "with_utm_source": 1000,
                "with_utm_campaign": 500,
                "top_utm_sources": [],
            },
        ]
        response = await suggest_conversion_goals(self.team)
        assert response.candidates[0].pct_with_utm_source == 100.0
        assert response.candidates[0].pct_with_utm_campaign == 50.0

    def test_default_excluded_events_includes_known_system_events(self):
        assert "$pageview" in DEFAULT_EXCLUDED_EVENTS
        assert "$autocapture" in DEFAULT_EXCLUDED_EVENTS
        assert "$identify" in DEFAULT_EXCLUDED_EVENTS
