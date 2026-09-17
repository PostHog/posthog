from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

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
        data = mock_notify.call_args[0][0]
        # (resource_type, resource_id) is the client's grouping key — without it every achievement
        # unlocked on the same day collapses into one inbox group regardless of track
        self.assertEqual(data.resource_type, "web_analytics")
        self.assertEqual(data.resource_id, "loyalty")

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

    def test_control_user_gets_no_compute(self) -> None:
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 50)),
            patch.object(tasks, "streak_arm_for_user", return_value="control"),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, self.user.id)
        self.assertFalse(WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(user=self.user).exists())


class TestAchievementEnqueueRecovery(SimpleTestCase):
    today = date(2026, 1, 2)

    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @contextmanager
    def _publish_fails(self) -> Iterator[MagicMock]:
        with patch.object(
            tasks.recompute_web_analytics_achievements, "delay", side_effect=RuntimeError("Publish failed")
        ) as publish:
            yield publish

    def test_publish_failure_allows_retry_and_success_retains_daily_debounce(self) -> None:
        with patch.object(tasks.recompute_web_analytics_achievements, "delay") as publish:
            publish.side_effect = RuntimeError("Publish failed")
            with self.assertRaisesMessage(RuntimeError, "Publish failed"):
                tasks.enqueue_recompute_web_analytics_achievements_debounced(12, None, self.today)
            publish.side_effect = None
            self.assertTrue(tasks.enqueue_recompute_web_analytics_achievements_debounced(12, None, self.today))
            self.assertFalse(tasks.enqueue_recompute_web_analytics_achievements_debounced(12, None, self.today))
            self.assertEqual(publish.call_count, 2)
            publish.assert_called_with(12, user_id=None)

    def test_cleanup_failure_does_not_hide_the_original_publish_error(self) -> None:
        with (
            self._publish_fails(),
            patch.object(tasks.cache, "delete", side_effect=RuntimeError("Cache unavailable")) as delete,
        ):
            with self.assertRaisesMessage(RuntimeError, "Publish failed"):
                tasks.enqueue_recompute_web_analytics_achievements_debounced(12, None, self.today)
        delete.assert_called_once()

    def test_cache_fail_open_does_not_delete_an_unclaimed_key_after_publish_failure(self) -> None:
        with (
            self._publish_fails(),
            patch.object(tasks.cache, "add", side_effect=RuntimeError("Cache unavailable")),
            patch.object(tasks.cache, "delete") as delete,
            patch.object(tasks, "capture_exception"),
        ):
            with self.assertRaisesMessage(RuntimeError, "Publish failed"):
                tasks.enqueue_recompute_web_analytics_achievements_debounced(12, None, self.today)
        delete.assert_not_called()
