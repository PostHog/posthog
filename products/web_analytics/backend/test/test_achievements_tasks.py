from collections.abc import Callable
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.exceptions import ClickHouseAtCapacity

from products.web_analytics.backend.achievements import tasks
from products.web_analytics.backend.achievements.evaluators import EvalContext
from products.web_analytics.backend.models import WebAnalyticsAchievementProgress, WebAnalyticsUserConfig
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

    def test_clickhouse_capacity_error_propagates_for_retry(self) -> None:
        # A capacity error must not be swallowed like other eval failures — it has to bubble up so the
        # task's autoretry backs off instead of dropping the recompute and re-saturating the cluster.
        def at_capacity(_ctx: EvalContext) -> int:
            raise ClickHouseAtCapacity()

        with self.assertRaises(ClickHouseAtCapacity):
            self._run_team(make_evaluators(cumulative_pageviews=at_capacity, conversions=lambda ctx: 0))

    def test_generic_eval_error_is_still_swallowed(self) -> None:
        def boom(_ctx: EvalContext) -> int:
            raise ValueError("unexpected")

        self._run_user(make_evaluators(loyal_days=boom))  # does not raise

    def test_control_user_gets_no_compute(self) -> None:
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 50)),
            patch.object(tasks, "streak_arm_for_user", return_value="control"),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, self.user.id)
        self.assertFalse(WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(user=self.user).exists())
