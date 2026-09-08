from datetime import UTC, datetime, timedelta

from products.metrics.backend.alert_state_machine import (
    AlertSnapshot,
    AlertState,
    CheckResult,
    NotificationAction,
    evaluate_alert_check,
)


def _snapshot(**overrides) -> AlertSnapshot:
    defaults = {
        "state": AlertState.NOT_FIRING,
        "evaluation_periods": 1,
        "datapoints_to_alarm": 1,
        "cooldown_minutes": 0,
        "last_notified_at": None,
        "snooze_until": None,
        "consecutive_failures": 0,
        "recent_events_breached": (),
    }
    defaults.update(overrides)
    return AlertSnapshot(**defaults)


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


class TestEvaluateAlertCheck:
    def test_breach_fires(self):
        outcome = evaluate_alert_check(_snapshot(), CheckResult(value=150.0, threshold_breached=True), NOW)
        assert outcome.new_state == AlertState.FIRING
        assert outcome.notification == NotificationAction.FIRE

    def test_clear_stays_not_firing(self):
        outcome = evaluate_alert_check(_snapshot(), CheckResult(value=50.0, threshold_breached=False), NOW)
        assert outcome.new_state == AlertState.NOT_FIRING
        assert outcome.notification == NotificationAction.NONE

    def test_firing_alert_resolves_on_clear(self):
        outcome = evaluate_alert_check(
            _snapshot(state=AlertState.FIRING), CheckResult(value=50.0, threshold_breached=False), NOW
        )
        assert outcome.new_state == AlertState.NOT_FIRING
        assert outcome.notification == NotificationAction.RESOLVE

    def test_n_of_m_requires_n_breaches(self):
        # 2-of-3: only one recent breach + this one = 2 breaches → fire.
        snap = _snapshot(evaluation_periods=3, datapoints_to_alarm=2, recent_events_breached=(True, False))
        outcome = evaluate_alert_check(snap, CheckResult(value=150.0, threshold_breached=True), NOW)
        assert outcome.notification == NotificationAction.FIRE

    def test_n_of_m_not_enough_breaches(self):
        # 2-of-3: this breach + two recent clears = 1 breach → no fire.
        snap = _snapshot(evaluation_periods=3, datapoints_to_alarm=2, recent_events_breached=(False, False))
        outcome = evaluate_alert_check(snap, CheckResult(value=150.0, threshold_breached=True), NOW)
        assert outcome.notification == NotificationAction.NONE
        assert outcome.new_state == AlertState.NOT_FIRING

    def test_error_counts_toward_broken(self):
        snap = _snapshot(consecutive_failures=4)
        outcome = evaluate_alert_check(
            snap,
            CheckResult(value=None, threshold_breached=False, error_message="boom"),
            NOW,
        )
        # 5th consecutive failure → BROKEN + notify.
        assert outcome.new_state == AlertState.BROKEN
        assert outcome.notification == NotificationAction.BROKEN

    def test_snoozed_alert_stays_snoozed(self):
        snap = _snapshot(state=AlertState.SNOOZED, snooze_until=NOW + timedelta(hours=1))
        outcome = evaluate_alert_check(snap, CheckResult(value=150.0, threshold_breached=True), NOW)
        assert outcome.new_state == AlertState.SNOOZED
        assert outcome.notification == NotificationAction.NONE
