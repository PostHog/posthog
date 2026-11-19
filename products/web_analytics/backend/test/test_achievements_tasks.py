from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection, transaction
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.user import User

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
            tasks.recompute_web_analytics_achievements(self.team, self.user)

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
            tasks.recompute_web_analytics_achievements(self.team, self.user)
        self.assertFalse(WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(user=self.user).exists())


@pytest.mark.django_db(transaction=True)
def test_user_recompute_skips_a_locked_progress_row_instead_of_waiting(team: Team, user: User) -> None:
    locked_row = WebAnalyticsAchievementProgress(team=team, user=user, track_key="explorer")
    locked_row.save()

    def recompute() -> None:
        tasks.recompute_web_analytics_achievements(team, user)

    def recompute_on_another_connection() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '1s'")
            recompute()
        finally:
            connection.close()

    with (
        patch.object(tasks, "EVALUATORS", make_evaluators(data_events=lambda ctx: 1, recordings_opened=lambda ctx: 1)),
        patch.object(tasks, "streak_arm_for_user", return_value="daily-only"),
    ):
        with transaction.atomic():
            WebAnalyticsAchievementProgress.objects.for_team(team.id).select_for_update().get(pk=locked_row.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(recompute_on_another_connection).result(timeout=10)

        stages = dict(
            WebAnalyticsAchievementProgress.objects.for_team(team.id)
            .filter(user=user)
            .values_list("track_key", "current_stage")
        )
        assert (stages["explorer"], stages["detective"]) == (0, 1)

        recompute()

    locked_row.refresh_from_db()
    assert locked_row.current_stage == 1
