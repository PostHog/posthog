from datetime import date

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.web_analytics.backend.achievements import backfill, tasks
from products.web_analytics.backend.achievements.definitions import TRACKS, TrackKey
from products.web_analytics.backend.achievements.evaluators import EvalContext, TrackEvaluation
from products.web_analytics.backend.models import WebAnalyticsAchievementProgress
from products.web_analytics.backend.test.achievements_test_utils import make_evaluators, make_incremental_evaluators


class TestBackfill(BaseTest):
    def test_seeds_stages_without_celebrations_and_skips_streak(self) -> None:
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 30)),
            patch.object(tasks, "INCREMENTAL_EVALUATORS", make_incremental_evaluators(cumulative_pageviews=1_000_000)),
        ):
            backfill.backfill_team(self.team.id)

        loyal = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(user=self.user, track_key="loyalty")
        self.assertEqual(loyal.current_stage, 3)
        self.assertEqual(loyal.state.get("pending_celebrations", []), [])
        self.assertEqual(len(loyal.state["unlocked_stages"]), 3)

        mighty = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key="traffic"
        )
        self.assertEqual(mighty.current_stage, 3)
        self.assertEqual(mighty.state.get("pending_celebrations", []), [])

        streak_exists = (
            WebAnalyticsAchievementProgress.objects.for_team(self.team.id)
            .filter(user=self.user, track_key="streak")
            .exists()
        )
        self.assertFalse(streak_exists)

    def test_backfill_leaves_last_computed_at_unset(self) -> None:
        # Backfilling must not advance last_computed_at, or it would suppress the same-day live
        # recompute (the recompute interval keys off last_computed_at).
        with (
            patch.object(tasks, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 5)),
            patch.object(tasks, "INCREMENTAL_EVALUATORS", make_incremental_evaluators()),
        ):
            backfill.backfill_team(self.team.id)
        loyal = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(user=self.user, track_key="loyalty")
        self.assertEqual(loyal.current_stage, 1)
        self.assertIsNone(loyal.last_computed_at)

    def test_backfill_keeps_partial_conversion_value_private(self) -> None:
        checkpoint: dict[str, object] = {"bootstrap": {"next_start": "2026-01-09T00:00:00+00:00"}}
        evaluation = TrackEvaluation(value=1000, checkpoint=checkpoint, complete=False)
        with patch.object(backfill, "evaluate_track", return_value=evaluation):
            touched = backfill._backfill_track(
                EvalContext(team=self.team, user=None, today=date.today(), arm=None),
                TRACKS[TrackKey.CONVERSIONS],
            )

        progress = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(
            user__isnull=True, track_key="conversions"
        )
        self.assertTrue(touched)
        self.assertEqual(progress.progress_value, 0)
        self.assertEqual(progress.current_stage, 0)
        self.assertEqual(progress.state["checkpoint"], checkpoint)

    @parameterized.expand([("incomplete", False), ("complete", True)])
    def test_backfill_does_not_overwrite_a_newer_conversion_checkpoint(self, _name: str, complete: bool) -> None:
        track = TRACKS[TrackKey.CONVERSIONS]
        ctx = EvalContext(team=self.team, user=None, today=date.today(), arm=None)
        progress = tasks.get_or_create_progress(ctx, track)
        winning_checkpoint = {"counted_through": "2026-01-02T00:05:00+00:00"}

        def evaluate_racing_recompute(_ctx: EvalContext, _track: object, _progress: object) -> TrackEvaluation:
            WebAnalyticsAchievementProgress.objects.for_team(self.team.id).filter(pk=progress.pk).update(
                progress_value=5,
                current_stage=3,
                state={"checkpoint": winning_checkpoint},
            )
            return TrackEvaluation(
                value=4,
                checkpoint={"counted_through": "2026-01-02T00:01:00+00:00"},
                complete=complete,
            )

        with patch.object(backfill, "evaluate_track", side_effect=evaluate_racing_recompute):
            touched = backfill._backfill_track(ctx, track)

        progress.refresh_from_db()
        self.assertFalse(touched)
        self.assertEqual(progress.progress_value, 5)
        self.assertEqual(progress.current_stage, 3)
        self.assertEqual(progress.state["checkpoint"], winning_checkpoint)
