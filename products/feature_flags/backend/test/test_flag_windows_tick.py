from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.temporal.common.registration import validate_registration

from products.feature_flags.backend.facade.temporal import TEMPORAL
from products.feature_flags.backend.flag_windows.tick import parse_watched_team_ids, tick_team, watched_team_ids
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.observation_window import FlagObservationWindow

STARTED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


def _filters(rollout: int) -> dict[str, Any]:
    return {"groups": [{"properties": [], "rollout_percentage": rollout}]}


class TestTickTeam(BaseTest):
    def _flag(self, rollout: int, **fields: Any) -> FeatureFlag:
        flag = FeatureFlag.objects.create(team=self.team, key="new-checkout", filters=_filters(rollout), **fields)
        # Creating the row logs an entry of its own, now.
        ActivityLog.objects.filter(team_id=self.team.pk, item_id=str(flag.pk)).delete()
        return flag

    def _edit(self, flag: FeatureFlag, before: int, after: int, at: datetime) -> None:
        FeatureFlag.objects.filter(pk=flag.pk).update(filters=_filters(after))
        entry = ActivityLog.objects.create(
            team_id=self.team.pk,
            scope="FeatureFlag",
            item_id=str(flag.pk),
            activity="updated",
            detail={"changes": [{"field": "filters", "before": _filters(before), "after": _filters(after)}]},
        )
        ActivityLog.objects.filter(pk=entry.pk).update(created_at=at)

    def _windows(self) -> list[str]:
        return [
            f"{window.config_before['filters']['groups'][0]['rollout_percentage']}% to "
            f"{window.config_after['filters']['groups'][0]['rollout_percentage']}%: {window.state} {window.close_reason}"
            for window in FlagObservationWindow.objects.for_team(self.team.pk).order_by("edited_at")
        ]

    def test_the_ticks_store_the_windows_that_the_edits_open_and_close(self) -> None:
        flag = self._flag(10)
        tick_team(self.team.pk, STARTED_AT)
        self._edit(flag, 10, 25, STARTED_AT + HOUR)
        tick_team(self.team.pk, STARTED_AT + 2 * HOUR)
        self._edit(flag, 25, 50, STARTED_AT + 4 * HOUR - timedelta(minutes=5))
        tick_team(self.team.pk, STARTED_AT + 4 * HOUR)
        tick_team(self.team.pk, STARTED_AT + 4 * HOUR + timedelta(minutes=5))

        assert self._windows() == ["10% to 25%: closed superseded", "25% to 50%: open None"]
        first, second = FlagObservationWindow.objects.for_team(self.team.pk).order_by("edited_at")
        assert second.previous_window_id == first.id

    def test_the_first_tick_opens_no_window_for_the_edits_before_it(self) -> None:
        flag = self._flag(10)
        self._edit(flag, 10, 25, STARTED_AT - HOUR)

        tick_team(self.team.pk, STARTED_AT)

        assert self._windows() == []

    def test_a_flag_with_the_watch_turned_off_opens_no_window(self) -> None:
        flag = self._flag(10, rollback_suggestions_disabled=True)
        tick_team(self.team.pk, STARTED_AT)
        self._edit(flag, 10, 25, STARTED_AT + HOUR)

        tick_team(self.team.pk, STARTED_AT + 2 * HOUR)

        assert self._windows() == []

    @patch("products.feature_flags.backend.flag_windows.tick.get_instance_region", return_value="US")
    @patch("products.feature_flags.backend.flag_windows.tick.posthoganalytics.get_feature_flag_payload")
    def test_watches_only_the_teams_whose_organization_approved_ai_data_processing(
        self, get_payload: Any, _region: Any
    ) -> None:
        organization = Organization.objects.create(name="No AI", is_ai_data_processing_approved=False)
        unapproved = Team.objects.create(organization=organization)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        get_payload.return_value = {"US": {"team_ids": [self.team.pk, unapproved.pk]}}

        assert watched_team_ids() == [self.team.pk]


class TestWatchedTeamIds(SimpleTestCase):
    @parameterized.expand(
        [
            ("the_entry_of_the_region", {"US": {"team_ids": [2, 3]}, "EU": {"team_ids": [4]}}, "US", {2, 3}),
            ("a_json_string", '{"US": {"team_ids": [2]}}', "US", {2}),
            ("no_entry_for_the_region", {"EU": {"team_ids": [4]}}, "US", set()),
            ("no_region", {"US": {"team_ids": [2]}}, None, set()),
            ("a_disabled_flag", None, "US", set()),
            ("ids_that_are_not_numbers", {"US": {"team_ids": ["2"]}}, "US", set()),
            ("a_boolean_id", {"US": {"team_ids": [True]}}, "US", set()),
        ]
    )
    def test_parse_watched_team_ids(self, _name: str, payload: object, region: str | None, expected: set[int]) -> None:
        assert parse_watched_team_ids(payload, region) == expected


def test_core_accepts_the_feature_flags_temporal_declaration() -> None:
    validate_registration("feature_flags", TEMPORAL)
