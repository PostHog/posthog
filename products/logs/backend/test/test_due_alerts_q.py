from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.logs.backend.alert_utils import due_alerts_q
from products.logs.backend.models import LogsAlertConfiguration

NOW = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(minutes=5)
FUTURE = NOW + timedelta(minutes=5)

State = LogsAlertConfiguration.State


class TestDueAlertsQ(BaseTest):
    def _is_due(self, alert: LogsAlertConfiguration) -> bool:
        q = due_alerts_q(NOW, broken_state=State.BROKEN, snoozed_state=State.SNOOZED)
        return LogsAlertConfiguration.objects.filter(q, id=alert.id).exists()

    @parameterized.expand(
        [
            ("due_past_next_check", {"next_check_at": PAST}, True),
            ("due_never_checked", {"next_check_at": None}, True),
            ("not_due_future_next_check", {"next_check_at": FUTURE}, False),
            ("disabled", {"enabled": False}, False),
            ("broken", {"state": State.BROKEN}, False),
            ("snoozed_state_active_snooze", {"state": State.SNOOZED, "snooze_until": FUTURE}, False),
            ("snoozed_state_expired_snooze", {"state": State.SNOOZED, "snooze_until": PAST}, True),
            ("snoozed_state_null_snooze", {"state": State.SNOOZED, "snooze_until": None}, True),
            (
                "non_snoozed_state_ignores_snooze_until",
                {"state": State.FIRING, "snooze_until": FUTURE},
                True,
            ),
        ]
    )
    def test_due_alerts_q(self, _name: str, overrides: dict, expected_due: bool) -> None:
        fields: dict = {"team": self.team, "name": "alert", "next_check_at": PAST, **overrides}
        alert = LogsAlertConfiguration.objects.create(**fields)
        assert self._is_due(alert) == expected_due
