from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.alerting.scheduling import due_alerts_q

from products.logs.backend.models import LogsAlertConfiguration

NOW = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(minutes=5)
FUTURE = NOW + timedelta(minutes=5)

State = LogsAlertConfiguration.State


class TestDueAlertsQ(BaseTest):
    def _is_due(self, alert: LogsAlertConfiguration, *, snoozed_state: str | None) -> bool:
        q = due_alerts_q(NOW, broken_state=State.BROKEN, snoozed_state=snoozed_state)
        return LogsAlertConfiguration.objects.filter(q, id=alert.id).exists()

    @parameterized.expand(
        [
            # Shared gating — identical in both snooze modes
            ("due_past_next_check", {"next_check_at": PAST}, State.SNOOZED, True),
            ("due_never_checked", {"next_check_at": None}, State.SNOOZED, True),
            ("not_due_future_next_check", {"next_check_at": FUTURE}, State.SNOOZED, False),
            ("disabled", {"enabled": False}, State.SNOOZED, False),
            ("broken", {"state": State.BROKEN}, State.SNOOZED, False),
            ("due_past_next_check_field_only", {"next_check_at": PAST}, None, True),
            ("due_never_checked_field_only", {"next_check_at": None}, None, True),
            ("not_due_future_next_check_field_only", {"next_check_at": FUTURE}, None, False),
            ("disabled_field_only", {"enabled": False}, None, False),
            ("broken_field_only", {"state": State.BROKEN}, None, False),
            # State+time snooze mode (logs): only the SNOOZED state with an active snooze is excluded
            ("snoozed_state_active_snooze", {"state": State.SNOOZED, "snooze_until": FUTURE}, State.SNOOZED, False),
            ("snoozed_state_expired_snooze", {"state": State.SNOOZED, "snooze_until": PAST}, State.SNOOZED, True),
            ("snoozed_state_null_snooze", {"state": State.SNOOZED, "snooze_until": None}, State.SNOOZED, True),
            (
                "non_snoozed_state_ignores_snooze_until",
                {"state": State.FIRING, "snooze_until": FUTURE},
                State.SNOOZED,
                True,
            ),
            # Field-only snooze mode (billing): any future snooze_until excludes, regardless of state
            ("field_only_future_snooze", {"state": State.FIRING, "snooze_until": FUTURE}, None, False),
            ("field_only_expired_snooze", {"state": State.FIRING, "snooze_until": PAST}, None, True),
            ("field_only_null_snooze", {"snooze_until": None}, None, True),
        ]
    )
    def test_due_alerts_q(self, _name: str, overrides: dict, snoozed_state: str | None, expected_due: bool) -> None:
        fields: dict = {"team": self.team, "name": "alert", "next_check_at": PAST, **overrides}
        alert = LogsAlertConfiguration.objects.create(**fields)
        assert self._is_due(alert, snoozed_state=snoozed_state) == expected_due
