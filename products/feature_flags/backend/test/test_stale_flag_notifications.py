from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.team import Team
from posthog.redis import get_client

from products.cdp.backend.facade.models import HogFunction, HogFunctionType
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.stale_flag_notifications import (
    EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
    EVIDENCE_NOT_CALLED_RECENTLY,
    STALE_FLAG_EVENT,
    notify_stale_flags_for_team,
    stale_notified_key,
    teams_subscribed_to_stale_flags,
)

PARTIAL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 50}]}
FULL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 100}]}
PRODUCE = "products.feature_flags.backend.stale_flag_notifications.produce_internal_event"


def stale_destination_filters(event: str = STALE_FLAG_EVENT) -> dict[str, Any]:
    return {"source": "internal-events", "events": [{"id": event, "type": "events"}]}


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
    def _create_flag(self, key: str, **kwargs: Any) -> FeatureFlag:
        kwargs.setdefault("active", True)
        kwargs.setdefault("filters", PARTIAL_ROLLOUT_FILTERS)
        return FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, **kwargs)

    def _events(self, produce: MagicMock) -> list[dict[str, Any]]:
        return [call.kwargs["event"].properties for call in produce.call_args_list]

    @patch(PRODUCE)
    def test_reports_a_flag_not_called_recently_with_the_reason_and_a_string_flag_id(
        self, produce: MagicMock
    ) -> None:
        flag = self._create_flag("checkout", last_called_at=timezone.now() - timedelta(days=45))

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

    @parameterized.expand(
        [
            ("called_recently", {"last_called_at": timezone.now() - timedelta(days=2)}),
            ("disabled", {"active": False, "last_called_at": timezone.now() - timedelta(days=45)}),
            ("archived", {"archived": True, "last_called_at": timezone.now() - timedelta(days=45)}),
            ("deleted", {"deleted": True, "last_called_at": timezone.now() - timedelta(days=45)}),
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
        flag = self._create_flag("checkout", last_called_at=timezone.now() - timedelta(days=45))

        assert notify_stale_flags_for_team(self.team.id) == 1
        # Still stale the next day
        assert notify_stale_flags_for_team(self.team.id, now=timezone.now() + timedelta(days=1)) == 0

        # Called again, then stale a second time
        flag.last_called_at = timezone.now() - timedelta(days=31)
        flag.save()
        assert notify_stale_flags_for_team(self.team.id) == 1

        assert [event["days_since_evidence"] for event in self._events(produce)] == [45, 31]

    @patch(PRODUCE)
    def test_keeps_the_marker_alive_while_the_flag_stays_stale(self, produce: MagicMock) -> None:
        flag = self._create_flag("checkout", last_called_at=timezone.now() - timedelta(days=45))
        assert notify_stale_flags_for_team(self.team.id) == 1

        # A marker about to expire is renewed by the next run, so a long stale period is reported once
        redis = get_client()
        redis.expire(stale_notified_key(flag.id), 10)
        assert notify_stale_flags_for_team(self.team.id) == 0

        assert redis.ttl(stale_notified_key(flag.id)) > 10
        assert produce.call_count == 1

    @patch(PRODUCE, side_effect=Exception("kafka is down"))
    def test_a_failed_send_is_retried_on_the_next_run(self, produce: MagicMock) -> None:
        self._create_flag("checkout", last_called_at=timezone.now() - timedelta(days=45))

        assert notify_stale_flags_for_team(self.team.id) == 0

        produce.side_effect = None
        assert notify_stale_flags_for_team(self.team.id) == 1

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
