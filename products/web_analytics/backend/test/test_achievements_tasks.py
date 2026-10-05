from collections.abc import Callable
from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.models.team.team import Team

from products.web_analytics.backend.achievements import tasks
from products.web_analytics.backend.achievements.evaluators import EvalContext, PriorProgress, TrackEvaluation
from products.web_analytics.backend.models import (
    WebAnalyticsAchievementProgress,
    WebAnalyticsUserConfig,
    WebAnalyticsVisit,
)
from products.web_analytics.backend.test.achievements_test_utils import (
    IncrementalEvaluator,
    make_evaluators,
    make_incremental_evaluators,
)


class TestRecomputeTask(BaseTest):
    def _run_user(self, evaluators: dict[str, Callable[[EvalContext], int]]) -> None:
        with (
            patch.object(tasks, "EVALUATORS", evaluators),
            patch.object(tasks, "streak_arm_for_user", return_value="daily-only"),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, self.user.id)

    def _run_team(self, incremental_evaluators: dict[str, IncrementalEvaluator]) -> None:
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators()),
            patch.object(tasks, "INCREMENTAL_EVALUATORS", incremental_evaluators),
        ):
            tasks.recompute_web_analytics_achievements(self.team.id, None)

    def _team_progress(self, track_key: str) -> WebAnalyticsAchievementProgress:
        return WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key=track_key
        )

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

    def test_recently_computed_team_track_is_not_recomputed(self) -> None:
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="traffic",
            current_stage=0,
            progress_value=0,
            state={},
            last_computed_at=timezone.now() - timedelta(hours=2),
        ).save()
        calls = {"count": 0}

        def pageviews(_ctx: EvalContext, _prior: PriorProgress) -> TrackEvaluation:
            calls["count"] += 1
            return TrackEvaluation(value=10_000, checkpoint={})

        self._run_team({**make_incremental_evaluators(), "cumulative_pageviews": pageviews})
        self.assertEqual(calls["count"], 0)

    def test_team_track_stores_the_evaluator_checkpoint(self) -> None:
        checkpoint: dict[str, object] = {"counted_through": "2026-01-02T00:00:00+00:00"}
        self._run_team(
            {
                **make_incremental_evaluators(),
                "cumulative_pageviews": lambda ctx, prior: TrackEvaluation(value=10_000, checkpoint=checkpoint),
            }
        )
        progress = self._team_progress("traffic")
        self.assertEqual(progress.current_stage, 1)
        self.assertEqual(progress.state["checkpoint"], checkpoint)

    @parameterized.expand([("racing_recompute", True), ("racing_backfill", False)])
    def test_overlapping_team_recompute_keeps_the_first_checkpoint(
        self, _name: str, bumps_last_computed_at: bool
    ) -> None:
        progress = WebAnalyticsAchievementProgress(
            team=self.team,
            user=None,
            track_key="traffic",
            current_stage=0,
            progress_value=100,
            state={},
            last_computed_at=timezone.now() - timedelta(days=1),
        )
        progress.save()
        winning_checkpoint = {"counted_through": "2026-01-02T00:05:00+00:00"}

        def pageviews_racing_another_run(_ctx: EvalContext, prior: PriorProgress) -> TrackEvaluation:
            row = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(pk=progress.pk)
            row.progress_value = 150
            if bumps_last_computed_at:
                row.last_computed_at = timezone.now()
            row.state = {"checkpoint": winning_checkpoint}
            row.save(update_fields=["progress_value", "last_computed_at", "state"])
            return TrackEvaluation(value=prior.value + 20, checkpoint={"counted_through": "2026-01-02T00:01:00+00:00"})

        self._run_team({**make_incremental_evaluators(), "cumulative_pageviews": pageviews_racing_another_run})
        progress.refresh_from_db()
        self.assertEqual(progress.progress_value, 150)
        self.assertEqual(progress.state["checkpoint"], winning_checkpoint)

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
                first_computed_at = self._progress("loyalty").last_computed_at
                with self.captureOnCommitCallbacks(execute=True):
                    self._run_user(make_evaluators(loyal_days=lambda ctx: 5))
        progress = self._progress("loyalty")
        self.assertEqual(progress.state["pending_celebrations"], [1])
        self.assertEqual(mock_notify.call_count, 1)
        self.assertEqual(progress.last_computed_at, first_computed_at)

    def test_unchanged_streak_value_still_records_new_visit_date(self) -> None:
        today = timezone.now().date()
        WebAnalyticsVisit(team=self.team, user=self.user, visit_date=today).save()
        WebAnalyticsAchievementProgress(
            team=self.team,
            user=self.user,
            track_key="streak",
            current_stage=0,
            progress_value=0,
            state={"streak": {"last_visit_date": (today - timedelta(days=1)).isoformat()}},
            last_computed_at=timezone.now() - timedelta(days=1),
        ).save()

        self._run_user(make_evaluators())
        self.assertEqual(self._progress("streak").state["streak"]["last_visit_date"], today.isoformat())

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


class TestSweep(BaseTest):
    def _team_with_traffic_progress(
        self, name: str, last_computed_at: datetime | None, current_stage: int = 0, visit_days_ago: int = 0
    ) -> int:
        team = Team.objects.create(organization=self.organization, name=name)
        WebAnalyticsVisit(
            team=team, user=self.user, visit_date=timezone.now().date() - timedelta(days=visit_days_ago)
        ).save()
        WebAnalyticsAchievementProgress(
            team=team,
            user=None,
            track_key="traffic",
            current_stage=current_stage,
            progress_value=0,
            state={},
            last_computed_at=last_computed_at,
        ).save()
        return team.id

    def _sweep(self, batch_size: int, kill_switch: KillSwitchLevel) -> list[int]:
        with (
            override_settings(WEB_ANALYTICS_ACHIEVEMENTS_SWEEP_BATCH_SIZE=batch_size),
            patch.object(tasks, "get_kill_switch_level", return_value=kill_switch),
            patch.object(tasks.recompute_web_analytics_achievements, "delay") as delay,
        ):
            tasks.sweep_web_analytics_achievement_team_tracks()
        return [call.args[0] for call in delay.call_args_list]

    @parameterized.expand(
        [
            ("all_due", 10, KillSwitchLevel.OFF, ["never", "two_days", "twenty_one_hours"]),
            ("batch_limit_keeps_oldest", 2, KillSwitchLevel.OFF, ["never", "two_days"]),
            ("disabled_by_zero_batch", 0, KillSwitchLevel.OFF, []),
            ("clickhouse_kill_switch", 10, KillSwitchLevel.LIGHT, []),
        ]
    )
    def test_sweep_enqueues_due_active_teams_oldest_first(
        self, _name: str, batch_size: int, kill_switch: KillSwitchLevel, expected: list[str]
    ) -> None:
        now = timezone.now()
        team_ids = {
            "twenty_one_hours": self._team_with_traffic_progress("21h", now - timedelta(hours=21)),
            "never": self._team_with_traffic_progress("never", None),
            "two_days": self._team_with_traffic_progress("2d", now - timedelta(days=2)),
            "fresh": self._team_with_traffic_progress("fresh", now - timedelta(hours=1)),
            "maxed": self._team_with_traffic_progress("maxed", now - timedelta(days=2), current_stage=5),
            "inactive": self._team_with_traffic_progress("inactive", now - timedelta(days=2), visit_days_ago=30),
        }
        self.assertEqual(self._sweep(batch_size, kill_switch), [team_ids[name] for name in expected])
