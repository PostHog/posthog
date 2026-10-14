from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_cutover import CutoverSkip, cut_over_team

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
State = LogsAlertConfiguration.State


class TestPlatformCutover(APIBaseTest):
    def _alert(self, **overrides: Any) -> LogsAlertConfiguration:
        fields: dict[str, Any] = {
            "team": self.team,
            "name": "Errors",
            "filters": {"severityLevels": ["error"]},
            "next_check_at": NOW + timedelta(minutes=3),
            "last_notified_at": NOW - timedelta(days=1),
            **overrides,
        }
        return LogsAlertConfiguration.objects.create(**fields)

    @parameterized.expand(
        [
            ("quiet", {}, "not_firing"),
            (
                "snoozed_keeps_checking_muted",
                {"state": State.SNOOZED, "snooze_until": NOW + timedelta(hours=1)},
                "not_firing",
            ),
            ("broken", {"state": State.BROKEN, "consecutive_failures": 5}, "broken"),
            ("disabled", {"enabled": False, "next_check_at": None}, "not_firing"),
        ]
    )
    def test_an_alert_moves_with_its_state_and_schedule(
        self, _name: str, overrides: dict[str, Any], platform_state: str
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at) == ("platform", NOW)
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            instance = platform_testing.alert_for(copy.id)
        assert (copy.owner, copy.consecutive_failures, copy.next_check_at) == (
            "platform",
            alert.consecutive_failures,
            alert.next_check_at,
        )
        assert instance is not None
        assert (instance.state, instance.last_notified_at, instance.snooze_until) == (
            platform_state,
            alert.last_notified_at,
            alert.snooze_until,
        )

    @parameterized.expand(
        [
            ("firing", {"state": State.FIRING}, CutoverSkip.FIRING),
            ("pending_resolve", {"state": State.PENDING_RESOLVE}, CutoverSkip.FIRING),
            ("check_due", {"next_check_at": NOW}, CutoverSkip.CHECK_DUE),
            ("never_scheduled", {"next_check_at": None}, CutoverSkip.CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_now_stays_with_logs(
        self, _name: str, overrides: dict[str, Any], reason: CutoverSkip
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == "source"

    def test_a_second_run_leaves_a_moved_alert_alone(self) -> None:
        self._alert()
        cut_over_team(self.team.id, now=NOW)

        (result,) = cut_over_team(self.team.id, now=NOW + timedelta(minutes=1))

        assert result.skipped == CutoverSkip.ALREADY_MOVED
