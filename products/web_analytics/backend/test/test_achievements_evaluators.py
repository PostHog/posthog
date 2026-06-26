from datetime import date, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Team, User

from products.web_analytics.backend.achievements.definitions import STREAK_ARM_DAILY, STREAK_ARM_WEEKLY
from products.web_analytics.backend.achievements.evaluators import (
    EvalContext,
    evaluate_cumulative_pageviews,
    evaluate_data_events,
    evaluate_loyal_days,
    evaluate_recordings_opened,
    evaluate_streak,
)
from products.web_analytics.backend.models import WebAnalyticsInteraction, WebAnalyticsVisit

TODAY = date(2026, 6, 15)


class TestAchievementEvaluators(BaseTest):
    def _add_visits(self, day_offsets: list[int], user: User | None = None) -> None:
        for offset in day_offsets:
            WebAnalyticsVisit(team=self.team, user=user or self.user, visit_date=TODAY - timedelta(days=offset)).save()

    @parameterized.expand(
        [
            ("three_consecutive_days", [0, 1, 2], STREAK_ARM_DAILY, 3),
            ("one_day_grace_freeze", [0, 2], STREAK_ARM_DAILY, 2),
            ("two_day_gap_breaks", [0, 3], STREAK_ARM_DAILY, 1),
            ("today_not_visited_starts_yesterday", [1, 2], STREAK_ARM_DAILY, 2),
            ("no_visits", [], STREAK_ARM_DAILY, 0),
            ("today_only", [0], STREAK_ARM_DAILY, 1),
            ("seven_in_a_row", [0, 1, 2, 3, 4, 5, 6], STREAK_ARM_DAILY, 7),
            ("weekly_two_consecutive_weeks", [0, 7], STREAK_ARM_WEEKLY, 2),
            ("weekly_gap_breaks", [0, 14], STREAK_ARM_WEEKLY, 1),
        ]
    )
    def test_streak(self, _name: str, offsets: list[int], arm: str, expected: int) -> None:
        self._add_visits(offsets)
        ctx = EvalContext(team=self.team, user=self.user, today=TODAY, arm=arm)
        self.assertEqual(evaluate_streak(ctx), expected)

    def test_loyal_days_counts_distinct_days(self) -> None:
        self._add_visits([0, 1, 2, 5, 10])
        ctx = EvalContext(team=self.team, user=self.user, today=TODAY, arm=None)
        self.assertEqual(evaluate_loyal_days(ctx), 5)

    def test_streak_is_per_user(self) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        self._add_visits([0, 1, 2], user=other_user)
        self._add_visits([0], user=self.user)
        ctx = EvalContext(team=self.team, user=self.user, today=TODAY, arm=STREAK_ARM_DAILY)
        self.assertEqual(evaluate_streak(ctx), 1)

    def test_interaction_counts_are_per_user_and_kind(self) -> None:
        WebAnalyticsInteraction(team=self.team, user=self.user, kind=WebAnalyticsInteraction.DATA, count=7).save()
        WebAnalyticsInteraction(team=self.team, user=self.user, kind=WebAnalyticsInteraction.RECORDING, count=3).save()
        ctx = EvalContext(team=self.team, user=self.user, today=TODAY, arm=None)
        self.assertEqual(evaluate_data_events(ctx), 7)
        self.assertEqual(evaluate_recordings_opened(ctx), 3)

    def test_interaction_count_zero_when_missing(self) -> None:
        ctx = EvalContext(team=self.team, user=self.user, today=TODAY, arm=None)
        self.assertEqual(evaluate_data_events(ctx), 0)

    @patch("products.web_analytics.backend.achievements.evaluators.WebOverviewQueryRunner")
    def test_cumulative_pageviews_sums_across_environments(self, mock_runner_cls: MagicMock) -> None:
        Team.objects.create(organization=self.organization, project=self.team.project, name="Second environment")

        def make_runner(team: Team, query: object) -> MagicMock:
            item = MagicMock()
            item.key = "views"
            item.value = 100
            runner = MagicMock()
            runner.calculate.return_value = MagicMock(results=[item])
            return runner

        mock_runner_cls.side_effect = make_runner
        ctx = EvalContext(team=self.team, user=None, today=TODAY, arm=None)
        # Both environments of the project contribute 100 each.
        self.assertEqual(evaluate_cumulative_pageviews(ctx), 200)
