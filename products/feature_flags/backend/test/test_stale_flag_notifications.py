from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team
from posthog.redis import get_client

from products.cdp.backend.facade.models import HogFunction, HogFunctionType
from products.feature_flags.backend.flag_status import (
    EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
    EVIDENCE_NOT_CALLED_RECENTLY,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.stale_flag_notifications import (
    MAX_NOTIFICATIONS_PER_TEAM_PER_RUN,
    STALE_FLAG_EVENT,
    notify_stale_flags_for_team,
    stale_notified_key,
    teams_subscribed_to_stale_flags,
)
from products.feature_flags.backend.tasks import notify_stale_feature_flags

PARTIAL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 50}]}
FULL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 100}]}
MODULE = "products.feature_flags.backend.stale_flag_notifications"
PRODUCE = f"{MODULE}.produce_internal_event"
FLUSH = f"{MODULE}.flush_internal_events_producer"
TASKS = "products.feature_flags.backend.tasks"


def stale_destination_filters(event: str = STALE_FLAG_EVENT) -> dict[str, Any]:
    return {"source": "internal-events", "events": [{"id": event, "type": "events"}]}


def stale_by_usage() -> dict[str, Any]:
    return {"last_called_at": timezone.now() - timedelta(days=45)}


class TestTeamsSubscribedToStaleFlags(BaseTest):
    def _create_destination(self, team: Team, **kwargs: Any) -> HogFunction:
        kwargs.setdefault("type", HogFunctionType.INTERNAL_DESTINATION)
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("filters", stale_destination_filters())
        kwargs.setdefault("name", "Stale flags to Slack")
        return HogFunction.objects.create(team=team, hog="return event", **kwargs)

    @parameterized.expand(
        [
            ("enabled_subscription", {}, True),
            ("disabled_subscription", {"enabled": False}, False),
            ("deleted_subscription", {"deleted": True}, False),
            (
                "subscribed_to_another_event",
                {"filters": stale_destination_filters("$activity_log_entry_created")},
                False,
            ),
            ("not_an_internal_destination", {"type": HogFunctionType.DESTINATION}, False),
        ]
    )
    def test_only_teams_with_a_live_subscription_are_evaluated(
        self, _name: str, overrides: dict[str, Any], expected: bool
    ) -> None:
        self._create_destination(self.team, **overrides)

        assert (self.team.id in teams_subscribed_to_stale_flags()) is expected

    def test_a_team_with_several_subscriptions_is_listed_once(self) -> None:
        self._create_destination(self.team)
        self._create_destination(self.team, name="Stale flags to Discord")

        assert teams_subscribed_to_stale_flags() == [self.team.id]


class TestNotifyStaleFlagsForTeam(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flush_patcher = patch(FLUSH, return_value=0)
        self.flush = flush_patcher.start()
        self.addCleanup(flush_patcher.stop)

    def _create_flag(self, key: str, **kwargs: Any) -> FeatureFlag:
        kwargs.setdefault("active", True)
        kwargs.setdefault("filters", PARTIAL_ROLLOUT_FILTERS)
        return FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, **kwargs)

    def _events(self, produce: MagicMock) -> list[dict[str, Any]]:
        return [call.kwargs["event"].properties for call in produce.call_args_list]

    @patch(PRODUCE)
    def test_reports_a_flag_not_called_recently_with_the_reason_and_a_string_flag_id(self, produce: MagicMock) -> None:
        flag = self._create_flag("checkout", **stale_by_usage())

        assert notify_stale_flags_for_team(self.team.id) == 1

        (event,) = self._events(produce)
        assert produce.call_args.kwargs["team_id"] == self.team.id
        assert produce.call_args.kwargs["event"].event == STALE_FLAG_EVENT
        assert event["flag_id"] == str(flag.id)
        assert event["flag_key"] == "checkout"
        assert event["evidence_class"] == EVIDENCE_NOT_CALLED_RECENTLY
        assert event["days_since_evidence"] == 45
        assert event["reason"] == "Flag has not been called in 45 days"

    @patch(PRODUCE)
    def test_reports_a_fully_rolled_out_flag_with_no_usage_data(self, produce: MagicMock) -> None:
        self._create_flag(
            "done-rolling-out", created_at=timezone.now() - timedelta(days=60), filters=FULL_ROLLOUT_FILTERS
        )

        assert notify_stale_flags_for_team(self.team.id) == 1

        (event,) = self._events(produce)
        assert event["evidence_class"] == EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA
        assert event["last_called_at"] is None

    @patch(PRODUCE)
    def test_reports_a_flag_whose_remote_config_column_is_null(self, produce: MagicMock) -> None:
        # The column is nullable; a NULL row is not remote config and must stay reportable
        self._create_flag("checkout", is_remote_configuration=None, **stale_by_usage())

        assert notify_stale_flags_for_team(self.team.id) == 1
        assert len(self._events(produce)) == 1

    @parameterized.expand(
        [
            ("called_recently", {"last_called_at": timezone.now() - timedelta(days=2)}),
            ("disabled", {**stale_by_usage(), "active": False}),
            # The archived_flag_must_be_disabled DB constraint forces active=False here
            ("archived", {**stale_by_usage(), "archived": True, "active": False}),
            ("deleted", {**stale_by_usage(), "deleted": True}),
            ("remote_config", {**stale_by_usage(), "is_remote_configuration": True}),
            (
                "young_with_no_usage_data",
                {"created_at": timezone.now() - timedelta(days=5), "filters": FULL_ROLLOUT_FILTERS},
            ),
        ]
    )
    @patch(PRODUCE)
    def test_does_not_report_a_flag_that_is_not_stale(
        self, _name: str, flag_kwargs: dict[str, Any], produce: MagicMock
    ) -> None:
        self._create_flag("not-stale", **flag_kwargs)

        assert notify_stale_flags_for_team(self.team.id) == 0
        produce.assert_not_called()

    @patch(PRODUCE)
    def test_reports_each_stale_period_once(self, produce: MagicMock) -> None:
        flag = self._create_flag("checkout", **stale_by_usage())

        assert notify_stale_flags_for_team(self.team.id) == 1
        assert notify_stale_flags_for_team(self.team.id) == 0

        # Called again, then stale a second time
        flag.last_called_at = timezone.now() - timedelta(days=31)
        flag.save()
        assert notify_stale_flags_for_team(self.team.id) == 1

        assert [event["days_since_evidence"] for event in self._events(produce)] == [45, 31]

    @patch(PRODUCE)
    def test_keeps_the_marker_alive_while_the_flag_stays_stale(self, produce: MagicMock) -> None:
        flag = self._create_flag("checkout", **stale_by_usage())
        assert notify_stale_flags_for_team(self.team.id) == 1

        # A marker about to expire is renewed by the next run, so a long stale period is reported once
        redis = get_client()
        redis.expire(stale_notified_key(flag.id), 10)
        assert notify_stale_flags_for_team(self.team.id) == 0

        assert redis.ttl(stale_notified_key(flag.id)) > 10
        assert produce.call_count == 1

    @patch(PRODUCE, side_effect=Exception("kafka is down"))
    def test_a_failed_send_is_retried_on_the_next_run(self, produce: MagicMock) -> None:
        flag = self._create_flag("checkout", **stale_by_usage())

        assert notify_stale_flags_for_team(self.team.id) == 0
        assert get_client().get(stale_notified_key(flag.id)) is None
        self.flush.assert_not_called()

        produce.side_effect = None
        assert notify_stale_flags_for_team(self.team.id) == 1

    @patch(PRODUCE)
    def test_an_undelivered_event_is_retried_on_the_next_run(self, produce: MagicMock) -> None:
        # The producer only queues the event; the broker's answer arrives through the result
        flag = self._create_flag("checkout", **stale_by_usage())
        produce.return_value.get.side_effect = Exception("delivery failed")

        assert notify_stale_flags_for_team(self.team.id) == 0

        self.flush.assert_called_once()
        produce.return_value.get.assert_called_once_with(timeout=0)
        assert get_client().get(stale_notified_key(flag.id)) is None

        produce.return_value.get.side_effect = None
        assert notify_stale_flags_for_team(self.team.id) == 1
        assert get_client().get(stale_notified_key(flag.id)) is not None

    @patch(PRODUCE)
    def test_spreads_a_backlog_over_several_runs_in_a_stable_order(self, produce: MagicMock) -> None:
        backlog = MAX_NOTIFICATIONS_PER_TEAM_PER_RUN + 2
        flags = [self._create_flag(f"flag-{i}", **stale_by_usage()) for i in range(backlog)]
        redis = get_client()

        assert notify_stale_flags_for_team(self.team.id) == MAX_NOTIFICATIONS_PER_TEAM_PER_RUN
        assert [event["flag_id"] for event in self._events(produce)] == [
            str(flag.id) for flag in flags[:MAX_NOTIFICATIONS_PER_TEAM_PER_RUN]
        ]

        # Flags already reported still get their marker refreshed while the rest of the backlog goes out
        redis.expire(stale_notified_key(flags[0].id), 10)
        assert notify_stale_flags_for_team(self.team.id) == 2
        assert redis.ttl(stale_notified_key(flags[0].id)) > 10

        assert notify_stale_flags_for_team(self.team.id) == 0
        assert sorted(event["flag_id"] for event in self._events(produce)) == sorted(str(flag.id) for flag in flags)

    @patch(PRODUCE)
    def test_only_looks_at_the_given_team(self, produce: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        FeatureFlag.objects.create(
            team=other_team,
            key="elsewhere",
            created_by=self.user,
            filters=PARTIAL_ROLLOUT_FILTERS,
            last_called_at=timezone.now() - timedelta(days=45),
        )

        assert notify_stale_flags_for_team(self.team.id) == 0
        produce.assert_not_called()


class TestNotifyStaleFeatureFlagsTask(BaseTest):
    def test_a_failing_team_does_not_stop_the_run_for_the_others(self) -> None:
        with (
            patch(f"{TASKS}.teams_subscribed_to_stale_flags", return_value=[1, 2]),
            patch(f"{TASKS}.notify_stale_flags_for_team", side_effect=[Exception("boom"), 0]) as notify,
            patch(f"{TASKS}.capture_exception") as capture,
        ):
            notify_stale_feature_flags()

        assert [call.args[0] for call in notify.call_args_list] == [1, 2]
        capture.assert_called_once()
