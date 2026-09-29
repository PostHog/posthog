from datetime import date, datetime, timedelta

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Element, Team, User

from products.actions.backend.models.action import Action
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_DAILY, STREAK_ARM_WEEKLY
from products.web_analytics.backend.achievements.evaluators import (
    EvalContext,
    PriorProgress,
    evaluate_conversions,
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


EMPTY_PRIOR = PriorProgress(value=0, last_computed_at=None, checkpoint={})


class TestTeamEvaluators(ClickhouseTestMixin, APIBaseTest):
    def _ctx(self) -> EvalContext:
        return EvalContext(team=self.team, user=None, today=date.today(), arm=None)

    def _pay_action(self, event: str | None) -> Action:
        return Action.objects.create(
            team=self.team,
            name="Clicked Pay",
            steps_json=[{"event": event, "tag_name": "button", "text": "Pay $10"}],
        )

    def _pay_click(self, timestamp: datetime | None = None, created_at: datetime | None = None) -> None:
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="d1",
            elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
            timestamp=timestamp or timezone.now() - timedelta(hours=2),
            created_at=created_at,
        )

    def test_cumulative_pageviews_counts_pageviews_across_environments(self) -> None:
        second_env = Team.objects.create(organization=self.organization, project=self.team.project, name="env 2")
        two_hours_ago = timezone.now() - timedelta(hours=2)
        _create_event(team=self.team, event="$pageview", distinct_id="d1", timestamp=two_hours_ago)
        _create_event(team=self.team, event="$screen", distinct_id="d1", timestamp=two_hours_ago)
        _create_event(team=self.team, event="custom_event", distinct_id="d1", timestamp=two_hours_ago)
        _create_event(team=second_env, event="$pageview", distinct_id="d2", timestamp=two_hours_ago)
        _create_event(team=self.team, event="$pageview", distinct_id="d1")
        flush_persons_and_events()

        self.assertEqual(evaluate_cumulative_pageviews(self._ctx(), EMPTY_PRIOR).value, 3)

    @parameterized.expand([("checkpoint",), ("legacy_last_computed_at",)])
    def test_cumulative_pageviews_adds_only_events_after_the_watermark(self, source: str) -> None:
        watermark = timezone.now() - timedelta(hours=3)
        _create_event(team=self.team, event="$pageview", distinct_id="d1", timestamp=watermark - timedelta(hours=2))
        _create_event(team=self.team, event="$pageview", distinct_id="d1", timestamp=watermark - timedelta(hours=2))
        _create_event(team=self.team, event="$pageview", distinct_id="d1", timestamp=watermark + timedelta(minutes=30))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="d1",
            timestamp=watermark - timedelta(hours=2),
            created_at=watermark + timedelta(minutes=30),
        )
        flush_persons_and_events()
        prior = (
            PriorProgress(value=100, last_computed_at=None, checkpoint={"counted_through": watermark.isoformat()})
            if source == "checkpoint"
            else PriorProgress(value=100, last_computed_at=watermark, checkpoint={})
        )

        evaluation = evaluate_cumulative_pageviews(self._ctx(), prior)

        self.assertEqual(evaluation.value, 102)
        assert evaluation.checkpoint is not None
        self.assertGreater(datetime.fromisoformat(str(evaluation.checkpoint["counted_through"])), watermark)

    @parameterized.expand([("named_event", "$autocapture"), ("any_event", None)])
    def test_conversions_returns_best_goal_conversion_count(self, _name: str, event: str | None) -> None:
        self._pay_action(event)
        self._pay_click()
        self._pay_click()
        flush_persons_and_events()

        self.assertEqual(evaluate_conversions(self._ctx(), EMPTY_PRIOR).value, 2)

    def test_conversions_falls_back_to_goal_count_without_conversions(self) -> None:
        self._pay_action("$autocapture")
        self.assertEqual(evaluate_conversions(self._ctx(), EMPTY_PRIOR).value, 1)

    @parameterized.expand(
        [
            ("unchanged_actions_add_new_arrivals", "unchanged", 5),
            ("edited_steps_rebuild", "edited_steps", 3),
            ("other_actions_rebuild", "other_actions", 3),
        ]
    )
    def test_conversions_keep_a_rolling_ninety_day_window(self, _name: str, change: str, expected: int) -> None:
        action = self._pay_action("$autocapture")
        prior_checkpoint = evaluate_conversions(self._ctx(), EMPTY_PRIOR).checkpoint
        assert prior_checkpoint is not None
        actions = prior_checkpoint["actions"]
        if change == "edited_steps":
            action.steps_json = [{"event": "$autocapture", "text": "Pay $10"}]
            action.save()
        elif change == "other_actions":
            actions = [[action.id + 1, "0"]]
        now = timezone.now()
        counted_through = now - timedelta(hours=3)
        late_day = (now - timedelta(days=2)).date().isoformat()
        expired_day = (now - timedelta(hours=1) - timedelta(days=90)).date().isoformat()
        self._pay_click()
        self._pay_click()
        self._pay_click(timestamp=now - timedelta(days=2), created_at=now - timedelta(hours=2))
        flush_persons_and_events()
        prior = PriorProgress(
            value=0,
            last_computed_at=counted_through,
            checkpoint={
                "actions": actions,
                "daily": {expired_day: [50], late_day: [2]},
                "counted_through": counted_through.isoformat(),
            },
        )

        evaluation = evaluate_conversions(self._ctx(), prior)

        self.assertEqual(evaluation.value, expected)
        assert evaluation.checkpoint is not None
        daily = evaluation.checkpoint["daily"]
        assert isinstance(daily, dict)
        self.assertNotIn(expired_day, daily)
