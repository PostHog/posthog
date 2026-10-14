from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration, upsert_configuration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import platform_upsert_of
from products.logs.backend.platform_cutover import CutoverSkip, RollbackSkip, cut_over_team, roll_back_team

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
            ("broken_never_scheduled", {"state": State.BROKEN, "next_check_at": None}, "broken"),
            ("disabled", {"enabled": False, "next_check_at": None}, "not_firing"),
            ("broken_past_due", {"state": State.BROKEN, "next_check_at": NOW - timedelta(hours=1)}, "broken"),
            (
                "snoozed_past_due",
                {"state": State.SNOOZED, "snooze_until": NOW + timedelta(hours=1), "next_check_at": NOW},
                "not_firing",
            ),
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
            max(alert.next_check_at or NOW, NOW + timedelta(minutes=1)),
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

    def test_a_refused_cutover_leaves_the_firing_platform_copy_as_it_was(self) -> None:
        alert = self._alert()
        upsert_configuration(platform_upsert_of(alert))
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            platform_testing.start_firing(copy.id, team_id=self.team.id, at=NOW - timedelta(hours=1))
        LogsAlertConfiguration.objects.filter(id=alert.id).update(enabled=False, next_check_at=None)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == CutoverSkip.PLATFORM_FIRING
        view = get_configuration(team_id=self.team.id, source_kinds=[SourceKind.LOGS], configuration_id=copy.id)
        assert view is not None and view.enabled
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    def test_a_second_run_leaves_a_moved_alert_alone(self) -> None:
        self._alert()
        cut_over_team(self.team.id, now=NOW)

        (result,) = cut_over_team(self.team.id, now=NOW + timedelta(minutes=1))

        assert result.skipped == CutoverSkip.ALREADY_MOVED

    def _moved(self, **overrides: Any) -> LogsAlertConfiguration:
        alert = self._alert(**overrides)
        cut_over_team(self.team.id, now=NOW)
        alert.refresh_from_db()
        return alert

    def test_rolling_back_after_the_shadow_carries_the_platform_state_back(self) -> None:
        alert = self._moved(state=State.BROKEN, consecutive_failures=5)
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at, alert.state, alert.consecutive_failures, alert.next_check_at) == (
            "source",
            later,
            State.BROKEN,
            5,
            later + timedelta(minutes=2),
        )
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    def test_rolling_back_keeps_an_active_logs_snooze(self) -> None:
        alert = self._moved()
        LogsAlertConfiguration.objects.filter(id=alert.id).update(
            state=State.SNOOZED, snooze_until=NOW + timedelta(days=30)
        )
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.state) == ("source", State.SNOOZED)

    @parameterized.expand(
        [
            ("never_moved", False, NOW + timedelta(days=8), RollbackSkip.NOT_MOVED),
            ("logs_check_due_during_shadow", True, NOW + timedelta(minutes=10), RollbackSkip.LOGS_CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_back_now_stays(
        self, _name: str, moved: bool, at: datetime, reason: RollbackSkip
    ) -> None:
        alert = self._moved() if moved else self._alert()

        (result,) = roll_back_team(self.team.id, now=at)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("platform" if moved else "source")
