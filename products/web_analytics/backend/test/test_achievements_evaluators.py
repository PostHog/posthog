from datetime import UTC, date, datetime, time, timedelta

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.models import Element, Team, User

from products.actions.backend.models.action import Action
from products.web_analytics.backend.achievements.definitions import STREAK_ARM_DAILY, STREAK_ARM_WEEKLY
from products.web_analytics.backend.achievements.evaluators import (
    EvalContext,
    PriorProgress,
    _action_fingerprints,
    _add_conversion_counts,
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

    def _pay_click(
        self, timestamp: datetime | None = None, created_at: datetime | None = None, team: Team | None = None
    ) -> None:
        _create_event(
            team=team or self.team,
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
            ("byte_limit", CHQueryErrorTooManyBytes("read limit", code=307), False),
            ("timeout", ClickHouseQueryTimeOut(), False),
            ("catchup_limit", CHQueryErrorTooManyBytes("read limit", code=307), True),
        ]
    )
    def test_conversions_resume_a_bounded_initial_scan_after_limit(
        self, _name: str, failure: Exception, catchup_fails: bool
    ) -> None:
        self._pay_action("$autocapture")
        first_now = timezone.now()
        old_timestamp = first_now - timedelta(days=10)
        recent_timestamp = first_now - timedelta(days=2)
        future_timestamp = first_now + timedelta(days=1)
        self._pay_click(timestamp=old_timestamp, created_at=old_timestamp)
        self._pay_click(timestamp=recent_timestamp, created_at=recent_timestamp)
        self._pay_click(timestamp=future_timestamp, created_at=first_now - timedelta(hours=2))
        flush_persons_and_events()

        attempts = 0

        def fail_full_window_once(*args: object, **kwargs: object):
            nonlocal attempts
            settings = kwargs["settings"]
            assert isinstance(settings, HogQLGlobalSettings)
            self.assertEqual(settings.timeout_overflow_mode, "throw")
            self.assertEqual(settings.read_overflow_mode, "throw")
            attempts += 1
            if attempts == 1 or (catchup_fails and attempts == 4):
                raise failure
            return execute_hogql_query(*args, **kwargs)

        with (
            patch("products.web_analytics.backend.achievements.evaluators.CONVERSIONS_LOOKBACK_DAYS", 14),
            patch(
                "products.web_analytics.backend.achievements.evaluators.execute_hogql_query",
                side_effect=fail_full_window_once,
            ),
        ):
            with patch("products.web_analytics.backend.achievements.evaluators.timezone.now", return_value=first_now):
                first = evaluate_conversions(self._ctx(), EMPTY_PRIOR)
            self.assertEqual(first.value, 1)
            self.assertFalse(first.complete)
            assert first.checkpoint is not None
            self.assertNotIn("counted_through", first.checkpoint)
            self.assertEqual(attempts, 1)

            self._pay_click(timestamp=old_timestamp, created_at=first_now)
            flush_persons_and_events()
            saw_catchup_checkpoint = False
            saw_tail_checkpoint = False
            final = first
            catchup_cutoff = None
            for sweep in range(12):
                with patch(
                    "products.web_analytics.backend.achievements.evaluators.timezone.now",
                    return_value=first_now + timedelta(hours=2, minutes=5 * sweep),
                ):
                    assert final.checkpoint is not None
                    final = evaluate_conversions(
                        self._ctx(),
                        PriorProgress(value=final.value, last_computed_at=None, checkpoint=final.checkpoint),
                    )
                    if attempts == 3:
                        self.assertFalse(final.complete)
                        assert final.checkpoint is not None
                        bootstrap = final.checkpoint["bootstrap"]
                        assert isinstance(bootstrap, dict)
                        self.assertEqual(bootstrap["phase"], "tail")
                        saw_tail_checkpoint = True
                    if catchup_fails and attempts == 4:
                        self.assertFalse(final.complete)
                        assert final.checkpoint is not None
                        bootstrap = final.checkpoint["bootstrap"]
                        assert isinstance(bootstrap, dict)
                        self.assertEqual(bootstrap["phase"], "catchup")
                        catchup_cutoff = bootstrap["created_until"]
                        saw_catchup_checkpoint = True
                    if final.complete:
                        break

        self.assertEqual(saw_catchup_checkpoint, catchup_fails)
        self.assertTrue(saw_tail_checkpoint)
        self.assertEqual(final.value, 4)
        self.assertTrue(final.complete)
        assert final.checkpoint is not None
        self.assertIn("counted_through", final.checkpoint)
        self.assertNotIn("bootstrap", final.checkpoint)
        if catchup_fails:
            self.assertEqual(final.checkpoint["counted_through"], catchup_cutoff)

        self._pay_click(
            timestamp=first_now + timedelta(hours=2),
            created_at=first_now + timedelta(hours=2, minutes=30),
        )
        flush_persons_and_events()
        with patch(
            "products.web_analytics.backend.achievements.evaluators.timezone.now",
            return_value=first_now + timedelta(hours=4),
        ):
            incremental = evaluate_conversions(
                self._ctx(), PriorProgress(value=final.value, last_computed_at=None, checkpoint=final.checkpoint)
            )
        self.assertEqual(incremental.value, 5)
        self.assertTrue(incremental.complete)

    def test_conversions_catchup_bounds_later_days_and_preserves_future_timestamps(self) -> None:
        action = self._pay_action("$autocapture")
        first_now = timezone.now()
        later = first_now + timedelta(days=4)
        self._pay_click(timestamp=first_now - timedelta(days=2), created_at=first_now + timedelta(days=1))
        self._pay_click(timestamp=first_now + timedelta(days=3), created_at=first_now + timedelta(days=3))
        self._pay_click(timestamp=first_now + timedelta(days=20), created_at=first_now + timedelta(days=3))
        flush_persons_and_events()

        created_since = first_now - timedelta(hours=2)
        created_until = later - timedelta(hours=1)
        catchup_end = datetime.combine(created_until.date() + timedelta(days=1), time.min, tzinfo=UTC)
        initial_window_start = datetime.combine((first_now - timedelta(days=13)).date(), time.min, tzinfo=UTC)
        checkpoint: dict[str, object] = {
            "actions": _action_fingerprints([action]),
            "daily": {},
            "bootstrap": {
                "next_start": initial_window_start.isoformat(),
                "end": (initial_window_start + timedelta(days=14)).isoformat(),
                "created_since": created_since.isoformat(),
                "created_until": created_until.isoformat(),
                "phase": "catchup",
                "chunk_hours": 24,
            },
        }

        split_final_slice = False

        def fail_wide_ingestion_slice(
            ctx: EvalContext,
            actions: list[Action],
            daily: dict[str, list[int]],
            since: datetime | None,
            until: datetime,
            earliest_timestamp: datetime,
            latest_timestamp: datetime | None = None,
        ) -> None:
            nonlocal split_final_slice
            if latest_timestamp is None and since is not None and until - since > timedelta(days=1):
                raise CHQueryErrorTooManyBytes("read limit", code=307)
            if (
                latest_timestamp is not None
                and latest_timestamp == catchup_end
                and latest_timestamp - earliest_timestamp > timedelta(hours=1)
            ):
                split_final_slice = True
                raise CHQueryErrorTooManyBytes("read limit", code=307)
            _add_conversion_counts(ctx, actions, daily, since, until, earliest_timestamp, latest_timestamp)

        with (
            patch("products.web_analytics.backend.achievements.evaluators.CONVERSIONS_LOOKBACK_DAYS", 14),
            patch("products.web_analytics.backend.achievements.evaluators.timezone.now", return_value=later),
            patch(
                "products.web_analytics.backend.achievements.evaluators._add_conversion_counts",
                side_effect=fail_wide_ingestion_slice,
            ),
        ):
            for _ in range(80):
                evaluation = evaluate_conversions(
                    self._ctx(), PriorProgress(value=1, last_computed_at=None, checkpoint=checkpoint)
                )
                assert evaluation.checkpoint is not None
                checkpoint = evaluation.checkpoint
                if evaluation.complete:
                    break

        self.assertTrue(evaluation.complete)
        self.assertTrue(split_final_slice)
        self.assertEqual(evaluation.value, 3)
        self.assertEqual(checkpoint["counted_through"], created_until.isoformat())

    def test_conversions_split_a_failed_chunk_without_duplicate_environment_counts(self) -> None:
        self._pay_action("$autocapture")
        second_env = Team.objects.create(organization=self.organization, project=self.team.project, name="env 2")
        now = timezone.now()
        timestamp = now - timedelta(days=10)
        self._pay_click(timestamp=timestamp, created_at=timestamp)
        self._pay_click(timestamp=timestamp, created_at=timestamp, team=second_env)
        flush_persons_and_events()

        attempts = 0

        def fail_second_environment_twice(*args: object, **kwargs: object):
            nonlocal attempts
            attempts += 1
            if attempts in (2, 4):
                raise CHQueryErrorTooManyBytes("read limit", code=307)
            return execute_hogql_query(*args, **kwargs)

        with (
            patch("products.web_analytics.backend.achievements.evaluators.CONVERSIONS_LOOKBACK_DAYS", 14),
            patch(
                "products.web_analytics.backend.achievements.evaluators.execute_hogql_query",
                side_effect=fail_second_environment_twice,
            ),
            patch("products.web_analytics.backend.achievements.evaluators.timezone.now", return_value=now),
        ):
            prior = EMPTY_PRIOR
            for _ in range(6):
                evaluation = evaluate_conversions(self._ctx(), prior)
                assert evaluation.checkpoint is not None
                if evaluation.complete:
                    break
                prior = PriorProgress(value=evaluation.value, last_computed_at=None, checkpoint=evaluation.checkpoint)
                if attempts == 4:
                    bootstrap = evaluation.checkpoint["bootstrap"]
                    assert isinstance(bootstrap, dict)
                    self.assertEqual(bootstrap["chunk_hours"], 84)

        self.assertTrue(evaluation.complete)
        self.assertEqual(evaluation.value, 2)
        self.assertGreater(attempts, 6)

    @parameterized.expand(
        [
            ("unchanged_actions_add_new_arrivals", "unchanged", 5),
            ("edited_steps_rebuild", "edited_steps", 4),
            ("other_actions_rebuild", "other_actions", 4),
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
        if change != "unchanged":
            self._pay_click(timestamp=now - timedelta(days=10), created_at=now - timedelta(days=10))
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
