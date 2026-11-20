from posthog.test.base import BaseTest
from unittest.mock import patch

from products.web_analytics.backend.achievements import backfill
from products.web_analytics.backend.models import WebAnalyticsAchievementProgress
from products.web_analytics.backend.test.achievements_test_utils import make_evaluators


class TestBackfill(BaseTest):
    def test_seeds_stages_without_celebrations_and_skips_streak(self) -> None:
        with patch.object(backfill, "EVALUATORS", make_evaluators(loyal_days=lambda ctx: 30)):
            backfill.backfill_team(self.team.id)

        loyal = WebAnalyticsAchievementProgress.objects.for_team(self.team.id).get(user=self.user, track_key="loyalty")
        self.assertEqual(loyal.current_stage, 3)
        self.assertEqual(loyal.state.get("pending_celebrations", []), [])
        self.assertEqual(len(loyal.state["unlocked_stages"]), 3)

        streak_exists = (
            WebAnalyticsAchievementProgress.objects.for_team(self.team.id)
            .filter(user=self.user, track_key="streak")
            .exists()
        )
        self.assertFalse(streak_exists)
