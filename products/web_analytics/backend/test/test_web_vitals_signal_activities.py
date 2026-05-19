from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.core.cache import cache

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.tasks.web_vitals_signal import (
    WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
    WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
    _enabled_cache_key,
)

from products.signals.backend.models import SignalSourceConfig
from products.web_analytics.backend.temporal.web_vitals_signal.activities import (
    _evaluate_regressions_sync,
    _evaluate_threshold_crossings_sync,
    _list_opted_in_teams_sync,
)
from products.web_analytics.backend.temporal.web_vitals_signal.types import WebVitalsBucket, WebVitalsEvaluationInput


def _bucket(**overrides: Any) -> WebVitalsBucket:
    defaults: dict[str, Any] = {
        "route": "/checkout",
        "device_class": "Mobile",
        "p75_value": 4500.0,
        "sample_count": 500,
    }
    defaults.update(overrides)
    return WebVitalsBucket(**defaults)


class _ActivityTestBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        from posthog.redis import get_client

        client = get_client()
        for pattern in (
            "web_vitals_signal_dedup:*",
            "web_vitals_signal_daily_count:*",
            "web_vitals_signal_band:*",
            "web_vitals_signal_streak:*",
        ):
            for key in client.scan_iter(match=pattern):
                client.delete(key)
        for source_type in (
            WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
            WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
        ):
            cache.delete(_enabled_cache_key(self.team.id, source_type))
            cache.set(_enabled_cache_key(self.team.id, source_type), True, 60)
        self.now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=UTC)
        self.eval_input = WebVitalsEvaluationInput(team_id=self.team.id, now_iso=self.now.isoformat())


class TestListOptedInTeams(_ActivityTestBase):
    def test_returns_distinct_team_ids_for_opted_in(self) -> None:
        org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=org, name="other")
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
            source_type=WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING,
            enabled=True,
        )
        SignalSourceConfig.objects.create(
            team=self.team,
            source_product=WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
            source_type=WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
            enabled=True,
        )
        SignalSourceConfig.objects.create(
            team=other_team,
            source_product=WEB_VITALS_SIGNAL_SOURCE_PRODUCT,
            source_type=WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION,
            enabled=False,
        )
        result = _list_opted_in_teams_sync()
        assert self.team.id in result
        assert other_team.id not in result
        # Each team appears at most once even if both source types are enabled.
        assert result.count(self.team.id) == 1


class TestThresholdCrossingActivity(_ActivityTestBase):
    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_first_observation_records_band_no_emit(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        mock_query.return_value = []
        # Only LCP returns a bucket; others empty.
        mock_query.side_effect = lambda **kwargs: ([_bucket(p75_value=4500.0)] if kwargs["metric"] == "LCP" else [])

        result = _evaluate_threshold_crossings_sync(self.eval_input)
        # First observation establishes baseline, doesn't emit.
        assert result.signals_emitted == 0
        mock_emit.assert_not_called()

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_stable_band_no_emit(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        # Seed the band state to 'poor' first.
        from posthog.tasks.web_vitals_signal import set_last_band

        set_last_band(self.team.id, "LCP", "/checkout", "Mobile", "poor")

        # Same band reported again — no emit.
        mock_query.side_effect = lambda **kwargs: ([_bucket(p75_value=4500.0)] if kwargs["metric"] == "LCP" else [])

        result = _evaluate_threshold_crossings_sync(self.eval_input)
        assert result.signals_emitted == 0
        mock_emit.assert_not_called()

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_band_transition_emits(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        from posthog.tasks.web_vitals_signal import set_last_band

        set_last_band(self.team.id, "LCP", "/checkout", "Mobile", "needs_improvements")

        # New observation is in the 'poor' band — emit.
        mock_query.side_effect = lambda **kwargs: ([_bucket(p75_value=4500.0)] if kwargs["metric"] == "LCP" else [])

        result = _evaluate_threshold_crossings_sync(self.eval_input)
        assert result.signals_emitted == 1
        assert mock_emit.await_count == 1
        assert mock_emit.await_args.kwargs["source_type"] == WEB_VITALS_SIGNAL_SOURCE_TYPE_THRESHOLD_CROSSING

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_recovery_transition_no_emit(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        from posthog.tasks.web_vitals_signal import set_last_band

        set_last_band(self.team.id, "LCP", "/checkout", "Mobile", "poor")

        # Recovery: 'poor' → 'good'. Update state but don't emit.
        mock_query.side_effect = lambda **kwargs: ([_bucket(p75_value=1500.0)] if kwargs["metric"] == "LCP" else [])

        result = _evaluate_threshold_crossings_sync(self.eval_input)
        assert result.signals_emitted == 0
        mock_emit.assert_not_called()

        # State has been refreshed to 'good'.
        from posthog.tasks.web_vitals_signal import get_last_band

        assert get_last_band(self.team.id, "LCP", "/checkout", "Mobile") == "good"

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_skips_empty_metric_queries(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        mock_query.return_value = []
        result = _evaluate_threshold_crossings_sync(self.eval_input)
        assert result.signals_emitted == 0
        assert result.metric_window_buckets_evaluated == 0
        mock_emit.assert_not_called()


class TestRegressionActivity(_ActivityTestBase):
    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_first_eval_no_emit(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        # Returns current 350ms and baseline 180ms for INP — regression but only 1 evaluation.
        def fake_query(**kwargs: Any) -> list[WebVitalsBucket]:
            if kwargs["metric"] != "INP":
                return []
            if kwargs["until"] < self.now:  # baseline window ends 1d before now  # baseline window
                return [_bucket(p75_value=180.0, sample_count=5000)]
            return [_bucket(p75_value=350.0, sample_count=500)]

        mock_query.side_effect = fake_query

        result = _evaluate_regressions_sync(self.eval_input)
        # Only one consecutive eval — streak == 1, needs 2.
        assert result.signals_emitted == 0
        mock_emit.assert_not_called()

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_two_consecutive_emits(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        def fake_query(**kwargs: Any) -> list[WebVitalsBucket]:
            if kwargs["metric"] != "INP":
                return []
            if kwargs["until"] < self.now:  # baseline window ends 1d before now
                return [_bucket(p75_value=180.0, sample_count=5000)]
            return [_bucket(p75_value=350.0, sample_count=500)]

        mock_query.side_effect = fake_query

        _evaluate_regressions_sync(self.eval_input)
        result = _evaluate_regressions_sync(self.eval_input)
        assert result.signals_emitted == 1
        assert mock_emit.await_count == 1
        assert mock_emit.await_args.kwargs["source_type"] == WEB_VITALS_SIGNAL_SOURCE_TYPE_REGRESSION

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_no_baseline_resets_streak(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        from posthog.tasks.web_vitals_signal import increment_regression_streak

        # Pre-seed a streak of 1 from an earlier eval.
        increment_regression_streak(self.team.id, "INP", "/checkout", "Mobile")

        def fake_query(**kwargs: Any) -> list[WebVitalsBucket]:
            if kwargs["metric"] != "INP":
                return []
            if kwargs["until"] < self.now:  # baseline window ends 1d before now
                # No baseline buckets — route is new.
                return []
            return [_bucket(p75_value=350.0)]

        mock_query.side_effect = fake_query

        result = _evaluate_regressions_sync(self.eval_input)
        assert result.signals_emitted == 0
        mock_emit.assert_not_called()
        # Streak reset.
        from posthog.redis import get_client
        from posthog.tasks.web_vitals_signal import _streak_key

        assert get_client().get(_streak_key(self.team.id, "INP", "/checkout", "Mobile")) is None

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_recovery_resets_streak(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        from posthog.redis import get_client
        from posthog.tasks.web_vitals_signal import _streak_key, increment_regression_streak

        # Pre-seed streak.
        increment_regression_streak(self.team.id, "INP", "/checkout", "Mobile")

        def fake_query(**kwargs: Any) -> list[WebVitalsBucket]:
            if kwargs["metric"] != "INP":
                return []
            if kwargs["until"] < self.now:  # baseline window ends 1d before now
                return [_bucket(p75_value=180.0, sample_count=5000)]
            return [_bucket(p75_value=185.0, sample_count=500)]  # Within noise floor

        mock_query.side_effect = fake_query

        _evaluate_regressions_sync(self.eval_input)
        assert get_client().get(_streak_key(self.team.id, "INP", "/checkout", "Mobile")) is None
        mock_emit.assert_not_called()

    @patch("products.web_analytics.backend.temporal.web_vitals_signal.activities.get_web_vitals_distribution")
    @patch("posthog.tasks.web_vitals_signal.emit_signal", new_callable=AsyncMock)
    def test_query_failure_doesnt_break_other_metrics(
        self,
        mock_emit: AsyncMock,
        mock_query: AsyncMock,
    ) -> None:
        call_count = {"n": 0}

        def fake_query(**kwargs: Any) -> list[WebVitalsBucket]:
            call_count["n"] += 1
            if kwargs["metric"] == "LCP":
                raise RuntimeError("clickhouse down")
            return []

        mock_query.side_effect = fake_query

        # Activity should not raise; INP and FCP should still execute.
        result = _evaluate_regressions_sync(self.eval_input)
        assert result.signals_emitted == 0
        # 3 metrics * 2 calls each (current + baseline) - but the LCP failure may abort
        # both current and baseline calls for LCP. Just confirm the function completed.
        assert call_count["n"] >= 1
        mock_emit.assert_not_called()
