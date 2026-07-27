from posthog.test.base import BaseTest
from unittest.mock import patch

from products.web_analytics.backend.achievements import backfill
from products.web_analytics.backend.models import WebAnalyticsAchievementProgress
from products.web_analytics.backend.test.achievements_test_utils import make_evaluators


class TestBackfill(BaseTest):
    def test_seeds_stages_without_celebrations_and_skips_streak(self) -> None:
        evaluators = make_evaluators(loyal_days=lambda ctx: 30, cumulative_pageviews=lambda ctx: 1_000_000)
        with patch.object(backfill, "EVALUATORS", evaluators):
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
        # recompute (the once-per-day gate keys off last_computed_at).
        with patch.object(backfill, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 5)):
            backfill.backfill_team(self.team.id)
        loyal = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(user=self.user, track_key="loyalty")
        self.assertEqual(loyal.current_stage, 1)
        self.assertIsNone(loyal.last_computed_at)
