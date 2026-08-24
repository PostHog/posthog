from datetime import UTC, datetime

from unittest import TestCase

from parameterized import parameterized

from products.tracing.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckResult,
    ControlPlaneOutcome,
    NotificationAction,
    apply_outcome,
    evaluate_alert_check,
)

FIRING = AlertState.FIRING
NOT_FIRING = AlertState.NOT_FIRING

NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)


def _snapshot(state: AlertState = NOT_FIRING, consecutive_failures: int = 0) -> AlertSnapshot:
    return AlertSnapshot(
        state=state,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
        last_notified_at=None,
        snooze_until=None,
        consecutive_failures=consecutive_failures,
        recent_events_breached=(),
    )


class TestEvaluateAlertCheck(TestCase):
    """Smoke-tests the field mapping in tracing's wrapper around the shared
    `evaluate_alert_check` — the exhaustive N-of-M / cooldown / broken-state matrix
    for the underlying logic is already covered by
    `products/alerts/backend/test/test_state_machine.py`.
    """

    @parameterized.expand(
        [
            ("breach_fires", True, None, FIRING, NotificationAction.FIRE),
            ("no_breach_stays_not_firing", False, None, NOT_FIRING, NotificationAction.NONE),
            ("error_keeps_state_and_notifies_error", False, "ClickHouse timeout", NOT_FIRING, NotificationAction.ERROR),
        ]
    )
    def test_maps_check_result_fields_through(
        self,
        _name: str,
        breached: bool,
        error: str | None,
        expected_state: AlertState,
        expected_action: NotificationAction,
    ) -> None:
        check = CheckResult(result_count=10 if breached else 0, threshold_breached=breached, error_message=error)
        outcome = evaluate_alert_check(_snapshot(), check, NOW)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_action

    def test_alert_state_matches_model_state(self) -> None:
        from products.tracing.backend.models import TracingAlertConfiguration

        assert set(AlertState) == {s.value for s in TracingAlertConfiguration.State}


class TestApplyOutcome(TestCase):
    """apply_outcome is the ONLY mutator of state/consecutive_failures — covered here so
    the invariant is locked in by tests, not just convention."""

    def test_applies_control_plane_outcome(self) -> None:
        from products.tracing.backend.models import TracingAlertConfiguration

        alert = TracingAlertConfiguration(state=FIRING.value, consecutive_failures=2, threshold_count=10)
        outcome = ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)
        fields = apply_outcome(alert, outcome)
        assert alert.state == NOT_FIRING.value
        assert alert.consecutive_failures == 0
        assert fields == ["state", "consecutive_failures"]

    def test_applies_check_outcome(self) -> None:
        from products.tracing.backend.models import TracingAlertConfiguration

        alert = TracingAlertConfiguration(state=NOT_FIRING.value, consecutive_failures=0, threshold_count=10)
        outcome = AlertCheckOutcome(
            new_state=FIRING,
            notification=NotificationAction.FIRE,
            consecutive_failures=0,
            update_last_notified_at=True,
            error_message=None,
        )
        fields = apply_outcome(alert, outcome)
        assert alert.state == FIRING.value
        assert alert.consecutive_failures == 0
        assert fields == ["state", "consecutive_failures"]
