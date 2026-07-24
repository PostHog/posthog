from collections.abc import Callable
from datetime import date, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.web_analytics.backend.achievements import tasks
from products.web_analytics.backend.achievements.evaluators import EvalContext
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)
from products.web_analytics.backend.test.achievements_test_utils import make_evaluators


class TestRecomputeTask(BaseTest):
    def _run_user(self, evaluators: dict[str, Callable[[EvalContext], int]]) -> None:
        with (
            patch.object(tasks, "EVALUATORS", evaluators),
            patch.object(tasks, "streak_arm_for_user", return_value="daily-only"),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, self.user.id)

    def _run_team(self, evaluators: dict[str, Callable[[EvalContext], int]]) -> None:
        with patch.object(tasks, "EVALUATORS", evaluators):
            tasks.recompute_web_analytics_achievements(self.team.id, None)

    def _progress(self, track_key: str) -> WebAnalyticsAchievementProgress:
        return WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(user=self.user, track_key=track_key)

    def test_crossing_multiple_stages_queues_each_celebration(self) -> None:
        self._run_user(make_evaluators(loyal_days=lambda ctx: 20))
        progress = self._progress("loyalty")
        self.assertEqual(progress.current_stage, 2)
        self.assertEqual(progress.state["pending_celebrations"], [1, 2])
        self.assertEqual(sorted(progress.state["unlocked_stages"].keys()), ["1", "2"])

    def test_maxed_track_is_not_recomputed(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team, user=self.user, track_key="loyalty", current_stage=5, progress_value=100, state={}
        ).save()
        calls = {"count": 0}

        def loyal(_ctx: EvalContext) -> int:
            calls["count"] += 1
            return 999

        self._run_user(make_evaluators(loyal_days=loyal))
        self.assertEqual(calls["count"], 0)
        self.assertEqual(self._progress("loyalty").current_stage, 5)

    def test_expensive_team_track_debounced_to_once_per_team_local_day(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="traffic",
            current_stage=0,
            progress_value=0,
            state={},
            last_computed_at=timezone.now(),
        ).save()
        calls = {"count": 0}

        def pageviews(_ctx: EvalContext) -> int:
            calls["count"] += 1
            return 10_000

        self._run_team(make_evaluators(cumulative_pageviews=pageviews))
        self.assertEqual(calls["count"], 0)

    def test_cheap_user_track_recomputes_intraday(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="loyalty",
            current_stage=0,
            progress_value=0,
            state={},
            last_computed_at=timezone.now(),
        ).save()
        calls = {"count": 0}

        def loyal(_ctx: EvalContext) -> int:
            calls["count"] += 1
            return 10

        self._run_user(make_evaluators(loyal_days=loyal))
        self.assertEqual(calls["count"], 1)
        self.assertEqual(self._progress("loyalty").current_stage, 1)

    def test_unlock_fires_best_effort_notification(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True):
            with patch.object(tasks, "create_notification") as mock_notify:
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
        self.assertEqual(mock_notify.call_count, 1)

    def test_unlock_notification_skipped_when_achievements_flag_disabled(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=False):
            with patch.object(tasks, "create_notification") as mock_notify:
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
        mock_notify.assert_not_called()

    def test_unlock_notification_skipped_when_user_opted_out(self) -> None:
        WebAnalyticsUserConfig(team=self.team, user=self.user, achievements_opt_out=True).save()
        with patch("posthoganalytics.feature_enabled", return_value=True):
            with patch.object(tasks, "create_notification") as mock_notify:
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
        mock_notify.assert_not_called()

    def test_duplicate_recompute_is_idempotent(self) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True):
            with patch.object(tasks, "create_notification") as mock_notify:
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
        progress = self._progress("loyalty")
        self.assertEqual(progress.state["pending_celebrations"], [1])
        self.assertEqual(mock_notify.call_count, 1)

    def test_recompute_does_not_resurrect_concurrent_ack(self) -> None:
        yesterday = timezone.now() - timedelta(days=1)
        progress = WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="loyalty",
            current_stage=1,
            progress_value=5,
            state={"pending_celebrations": [1], "unlocked_stages": {"1": yesterday.isoformat()}},
            last_computed_at=yesterday,
        )
        progress.save()

        def loyal_that_acks(_ctx: EvalContext) -> int:
            # Simulate the user acknowledging stage 1 while the (slow) evaluator runs — i.e. before
            # the locked write in _apply_progress re-reads state.
            row = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(pk=progress.pk)
            row.state = {**row.state, "pending_celebrations": []}
            row.save(update_fields=["state"])
            return 5

        self._run_user(make_evaluators(loyal_days=loyal_that_acks))
        progress.refresh_from_db()
        self.assertEqual(progress.state["pending_celebrations"], [])

    def _traffic(self) -> WebAnalyticsAchievementProgress:
        return WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key="traffic"
        )

    @parameterized.expand(
        [
            # A team with a running total and a cursor adds only the bounded delta to its total.
            ("seeded_accumulates", {"total": 10_000, "cursor": True}, 10_000, 5_000, True, 15_000),
            # First touch (no cursor) plants the cursor without counting — no unbounded full scan.
            ("first_touch_plants_cursor", {}, 0, 0, False, 0),
            # A backfilled team (progress_value set, cursor but no state total) accumulates on top of
            # its historical base rather than resetting to zero.
            ("backfilled_base_preserved", {"cursor": True}, 20_000, 5_000, True, 25_000),
        ]
    )
    def test_cumulative_pageviews_accumulates_bounded_delta(
        self,
        _name: str,
        state_spec: dict,
        progress_value: int,
        delta: int,
        expect_count_called: bool,
        expected_total: int,
    ) -> None:
        yesterday = timezone.now() - timedelta(days=1)
        state: dict = {}
        pageviews: dict = {}
        if "total" in state_spec:
            pageviews["total"] = state_spec["total"]
        if state_spec.get("cursor"):
            pageviews["counted_through"] = yesterday.isoformat()
        if pageviews:
            state["pageviews"] = pageviews
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="traffic",
            current_stage=0,
            progress_value=progress_value,
            state=state,
            last_computed_at=yesterday,
        ).save()

        with patch.object(tasks, "count_cumulative_pageviews_since", return_value=delta) as mock_count:
            self._run_team(make_evaluators())

        self.assertEqual(mock_count.called, expect_count_called)
        traffic = self._traffic()
        self.assertEqual(traffic.progress_value, expected_total)
        self.assertEqual(traffic.state["pageviews"]["total"], expected_total)
        # The cursor always advances so the next run's window starts where this one ended.
        self.assertGreater(datetime.fromisoformat(traffic.state["pageviews"]["counted_through"]), yesterday)

    @parameterized.expand([("prompt_when_zero", 0, None), ("staggered_when_positive", 300, 300)])
    def test_enqueue_countdown_controls_apply_async(self, _name: str, countdown: int, expected: int | None) -> None:
        with (
            patch.object(tasks.cache, "add", return_value=True),
            patch.object(tasks.recompute_web_analytics_achievements, "apply_async") as mock_async,
        ):
            tasks.enqueue_recompute_web_analytics_achievements_debounced(
                self.team.id, None, date(2026, 6, 15), countdown=countdown
            )
        mock_async.assert_called_once_with(args=[self.team.id], kwargs={"user_id": None}, countdown=expected)

    def test_sweep_staggers_enqueues(self) -> None:
        WebAnalyticsVisit(team=self.team, user=self.user, visit_date=timezone.now().date()).save()
        with patch.object(tasks, "enqueue_recompute_web_analytics_achievements_debounced") as mock_enqueue:
            tasks.sweep_web_analytics_achievement_team_tracks()
        mock_enqueue.assert_called_once()
        countdown = mock_enqueue.call_args.kwargs["countdown"]
        self.assertGreaterEqual(countdown, 0)
        self.assertLessEqual(countdown, tasks.SWEEP_STAGGER_SECONDS)

    def test_control_user_gets_no_compute(self) -> None:
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 50)),
            patch.object(tasks, "streak_arm_for_user", return_value="control"),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, self.user.id)
        self.assertFalse(WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(user=self.user).exists())
