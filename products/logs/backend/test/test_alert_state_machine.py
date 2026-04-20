from datetime import UTC, datetime, timedelta

from unittest import TestCase

from parameterized import parameterized

from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckResult,
    ControlPlaneOutcome,
    InvalidTransition,
    NotificationAction,
    apply_disable,
    apply_enable,
    apply_outcome,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
    evaluate_alert_check,
)

BROKEN = AlertState.BROKEN
ERRORED = AlertState.ERRORED
FIRING = AlertState.FIRING
NOT_FIRING = AlertState.NOT_FIRING
PENDING_RESOLVE = AlertState.PENDING_RESOLVE
SNOOZED = AlertState.SNOOZED

NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)


def _snapshot(
    state: AlertState = NOT_FIRING,
    evaluation_periods: int = 1,
    datapoints_to_alarm: int = 1,
    cooldown_minutes: int = 0,
    last_notified_at: datetime | None = None,
    snooze_until: datetime | None = None,
    consecutive_failures: int = 0,
    recent_events_breached: tuple[bool, ...] | None = None,
) -> AlertSnapshot:
    return AlertSnapshot(
        state=state,
        evaluation_periods=evaluation_periods,
        datapoints_to_alarm=datapoints_to_alarm,
        cooldown_minutes=cooldown_minutes,
        last_notified_at=last_notified_at,
        snooze_until=snooze_until,
        consecutive_failures=consecutive_failures,
        recent_events_breached=recent_events_breached or (),
    )


def _check(breached: bool = False, error: str | None = None) -> CheckResult:
    return CheckResult(
        result_count=100 if breached else 0,
        threshold_breached=breached,
        error_message=error,
    )


class TestNotFiringTransitions(TestCase):
    @parameterized.expand(
        [
            ("1_of_1_breach", 1, 1, (), True, FIRING, NotificationAction.FIRE),
            ("1_of_1_no_breach", 1, 1, (), False, NOT_FIRING, NotificationAction.NONE),
            ("2_of_3_breach_met", 2, 3, (True, False), True, FIRING, NotificationAction.FIRE),
            ("2_of_3_breach_not_met", 2, 3, (False, False), True, NOT_FIRING, NotificationAction.NONE),
            ("3_of_5_breach_met", 3, 5, (True, True, False, True), True, FIRING, NotificationAction.FIRE),
            ("3_of_5_breach_not_met", 3, 5, (False, False, False, False), True, NOT_FIRING, NotificationAction.NONE),
            ("first_ever_check_breach", 1, 1, (), True, FIRING, NotificationAction.FIRE),
            ("first_ever_check_no_breach", 1, 1, (), False, NOT_FIRING, NotificationAction.NONE),
            ("first_check_2_of_3_insufficient", 2, 3, (), True, NOT_FIRING, NotificationAction.NONE),
        ]
    )
    def test_not_firing_transitions(
        self,
        _name: str,
        n: int,
        m: int,
        recent: tuple[bool, ...],
        breached: bool,
        expected_state: AlertState,
        expected_action: NotificationAction,
    ) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            datapoints_to_alarm=n,
            evaluation_periods=m,
            recent_events_breached=recent,
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=breached), NOW)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_action


class TestFiringTransitions(TestCase):
    @parameterized.expand(
        [
            ("still_breaching_1_of_1", 1, 1, (), True, FIRING, NotificationAction.NONE),
            ("still_breaching_2_of_3", 2, 3, (True, True), True, FIRING, NotificationAction.NONE),
            ("clears_1_of_1", 1, 1, (), False, NOT_FIRING, NotificationAction.RESOLVE),
            # N-of-M only governs firing — resolution is always immediate on first OK check
            ("clears_immediately_2_of_3", 2, 3, (True, True), False, NOT_FIRING, NotificationAction.RESOLVE),
        ]
    )
    def test_firing_transitions(
        self,
        _name: str,
        n: int,
        m: int,
        recent: tuple[bool, ...],
        breached: bool,
        expected_state: AlertState,
        expected_action: NotificationAction,
    ) -> None:
        snapshot = _snapshot(
            state=FIRING,
            datapoints_to_alarm=n,
            evaluation_periods=m,
            recent_events_breached=recent,
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=breached), NOW)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_action


class TestPendingResolveTransitions(TestCase):
    @parameterized.expand(
        [
            # Any non-breaching check from PENDING_RESOLVE resolves immediately
            ("clears_fully", 2, 3, (False, True), False, NOT_FIRING, NotificationAction.RESOLVE),
            # Re-breach goes back to FIRING
            ("re_breaches", 2, 3, (False, True), True, FIRING, NotificationAction.NONE),
            # Non-breaching resolves immediately regardless of recent history
            ("mixed_resolves_immediately", 2, 3, (True, True), False, NOT_FIRING, NotificationAction.RESOLVE),
        ]
    )
    def test_pending_resolve_transitions(
        self,
        _name: str,
        n: int,
        m: int,
        recent: tuple[bool, ...],
        breached: bool,
        expected_state: AlertState,
        expected_action: NotificationAction,
    ) -> None:
        snapshot = _snapshot(
            state=PENDING_RESOLVE,
            datapoints_to_alarm=n,
            evaluation_periods=m,
            recent_events_breached=recent,
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=breached), NOW)
        assert outcome.new_state == expected_state
        assert outcome.notification == expected_action


class TestCooldownSuppression(TestCase):
    def test_suppresses_fire_notification(self) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            cooldown_minutes=10,
            last_notified_at=NOW - timedelta(minutes=5),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.new_state == FIRING
        assert outcome.notification == NotificationAction.NONE
        assert outcome.update_last_notified_at is False

    def test_suppresses_resolve_notification(self) -> None:
        snapshot = _snapshot(
            state=FIRING,
            cooldown_minutes=10,
            last_notified_at=NOW - timedelta(minutes=5),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.new_state == NOT_FIRING
        assert outcome.notification == NotificationAction.NONE

    def test_expired_cooldown_allows_notification(self) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            cooldown_minutes=10,
            last_notified_at=NOW - timedelta(minutes=15),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.new_state == FIRING
        assert outcome.notification == NotificationAction.FIRE
        assert outcome.update_last_notified_at is True

    def test_zero_cooldown_never_suppresses(self) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            cooldown_minutes=0,
            last_notified_at=NOW - timedelta(seconds=1),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.notification == NotificationAction.FIRE

    def test_no_prior_notification_never_suppresses(self) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            cooldown_minutes=10,
            last_notified_at=None,
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.notification == NotificationAction.FIRE


class TestErrorHandling(TestCase):
    def test_error_transitions_to_errored(self) -> None:
        snapshot = _snapshot(state=NOT_FIRING)
        outcome = evaluate_alert_check(snapshot, _check(error="ClickHouse timeout"), NOW)
        assert outcome.new_state == ERRORED
        assert outcome.notification == NotificationAction.NONE
        assert outcome.error_message == "ClickHouse timeout"

    def test_error_increments_consecutive_failures(self) -> None:
        snapshot = _snapshot(state=NOT_FIRING, consecutive_failures=2)
        outcome = evaluate_alert_check(snapshot, _check(error="timeout"), NOW)
        assert outcome.consecutive_failures == 3

    def test_success_resets_consecutive_failures(self) -> None:
        snapshot = _snapshot(state=NOT_FIRING, consecutive_failures=3)
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.consecutive_failures == 0

    def test_error_from_firing_state(self) -> None:
        snapshot = _snapshot(state=FIRING)
        outcome = evaluate_alert_check(snapshot, _check(error="timeout"), NOW)
        assert outcome.new_state == ERRORED

    def test_errored_recovery_with_breach(self) -> None:
        snapshot = _snapshot(state=ERRORED)
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.new_state == FIRING
        assert outcome.notification == NotificationAction.FIRE

    def test_errored_recovery_without_breach(self) -> None:
        snapshot = _snapshot(state=ERRORED)
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.new_state == NOT_FIRING
        assert outcome.notification == NotificationAction.NONE


class TestBrokenTransition(TestCase):
    @parameterized.expand(
        [
            ("below_threshold", 3, ERRORED, 4),
            ("one_below_threshold", 4, BROKEN, 5),
            ("at_threshold", 5, BROKEN, 6),
        ]
    )
    def test_error_trips_broken_at_max_consecutive_failures(
        self,
        _name: str,
        prior_failures: int,
        expected_state: AlertState,
        expected_failures: int,
    ) -> None:
        snapshot = _snapshot(state=NOT_FIRING, consecutive_failures=prior_failures)
        outcome = evaluate_alert_check(snapshot, _check(error="ClickHouse timeout"), NOW)
        assert outcome.new_state == expected_state
        assert outcome.consecutive_failures == expected_failures
        assert outcome.error_message == "ClickHouse timeout"

    # Scheduler excludes BROKEN so these shouldn't occur, but belt-and-braces:
    # a BROKEN alert must not silently self-heal and its failure counter stays frozen
    # until an explicit unbreak path resets it.
    @parameterized.expand(
        [
            ("on_error", _check(error="still down")),
            ("on_success", _check(breached=False)),
        ]
    )
    def test_broken_stays_broken(self, _name: str, check: CheckResult) -> None:
        snapshot = _snapshot(state=BROKEN, consecutive_failures=5)
        outcome = evaluate_alert_check(snapshot, check, NOW)
        assert outcome.new_state == BROKEN
        assert outcome.notification == NotificationAction.NONE
        assert outcome.consecutive_failures == 5


class TestSnooze(TestCase):
    def test_active_snooze_stays_snoozed(self) -> None:
        snapshot = _snapshot(
            state=SNOOZED,
            snooze_until=NOW + timedelta(hours=1),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.new_state == SNOOZED
        assert outcome.notification == NotificationAction.NONE

    def test_expired_snooze_resumes_as_not_firing(self) -> None:
        snapshot = _snapshot(
            state=SNOOZED,
            snooze_until=NOW - timedelta(minutes=1),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.new_state == NOT_FIRING

    def test_expired_snooze_with_breach_fires(self) -> None:
        snapshot = _snapshot(
            state=SNOOZED,
            snooze_until=NOW - timedelta(minutes=1),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.new_state == FIRING
        assert outcome.notification == NotificationAction.FIRE

    def test_snooze_with_none_expiry_resumes_not_firing(self) -> None:
        snapshot = _snapshot(
            state=SNOOZED,
            snooze_until=None,
        )
        # snooze_until=None means it doesn't expire by time, treat as expired
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.new_state == NOT_FIRING


class TestEdgeCases(TestCase):
    def test_non_breaching_check_resolves_immediately(self) -> None:
        snapshot = _snapshot(state=FIRING, datapoints_to_alarm=1, evaluation_periods=1)
        outcome = evaluate_alert_check(snapshot, _check(breached=False), NOW)
        assert outcome.new_state == NOT_FIRING
        assert outcome.notification == NotificationAction.RESOLVE

    def test_window_truncated_to_m(self) -> None:
        snapshot = _snapshot(
            state=NOT_FIRING,
            datapoints_to_alarm=2,
            evaluation_periods=3,
            recent_events_breached=(True, True, True, True, True),
        )
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        # Window is [True, True, True] (truncated to M=3), 3 breaches >= N=2
        assert outcome.new_state == FIRING

    def test_update_last_notified_at_on_fire(self) -> None:
        snapshot = _snapshot(state=NOT_FIRING)
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.update_last_notified_at is True

    def test_no_update_last_notified_at_on_suppress(self) -> None:
        snapshot = _snapshot(state=FIRING)
        outcome = evaluate_alert_check(snapshot, _check(breached=True), NOW)
        assert outcome.update_last_notified_at is False

    def test_outcome_is_frozen_dataclass(self) -> None:
        snapshot = _snapshot()
        outcome = evaluate_alert_check(snapshot, _check(), NOW)
        assert isinstance(outcome, AlertCheckOutcome)

    def test_alert_state_matches_model_state(self) -> None:
        from products.logs.backend.models import LogsAlertConfiguration

        assert set(AlertState) == {s.value for s in LogsAlertConfiguration.State}


class TestApplyUserReset(TestCase):
    def test_broken_to_not_firing_resets_failures(self) -> None:
        outcome = apply_user_reset(_snapshot(state=BROKEN, consecutive_failures=5))
        assert outcome == ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)

    @parameterized.expand(
        [
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
            ("pending_resolve", PENDING_RESOLVE),
            ("errored", ERRORED),
            ("snoozed", SNOOZED),
        ]
    )
    def test_rejects_non_broken_state(self, _name: str, state: AlertState) -> None:
        with self.assertRaises(InvalidTransition) as ctx:
            apply_user_reset(_snapshot(state=state))
        assert "Only broken alerts" in str(ctx.exception)


class TestApplyDisable(TestCase):
    @parameterized.expand(
        [
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
            ("errored", ERRORED),
            ("snoozed", SNOOZED),
            # BROKEN is intentionally included — disabling a broken alert is legal;
            # it parks the alert without the user needing to reset first.
            ("broken", BROKEN),
        ]
    )
    def test_any_state_transitions_to_not_firing(self, _name: str, state: AlertState) -> None:
        outcome = apply_disable(_snapshot(state=state, consecutive_failures=3))
        assert outcome.new_state == NOT_FIRING
        # consecutive_failures is preserved so a re-enable without an explicit reset
        # doesn't silently wipe forensic information.
        assert outcome.consecutive_failures == 3


class TestApplyEnable(TestCase):
    @parameterized.expand(
        [
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
            ("errored", ERRORED),
            ("snoozed", SNOOZED),
            ("broken", BROKEN),
        ]
    )
    def test_any_state_transitions_to_not_firing_with_clean_counter(self, _name: str, state: AlertState) -> None:
        outcome = apply_enable(_snapshot(state=state, consecutive_failures=4))
        assert outcome == ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)


class TestApplySnooze(TestCase):
    @parameterized.expand(
        [
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
            ("errored", ERRORED),
            ("broken", BROKEN),
            ("pending_resolve", PENDING_RESOLVE),
        ]
    )
    def test_preserves_failures_and_sets_snoozed(self, _name: str, state: AlertState) -> None:
        outcome = apply_snooze(_snapshot(state=state, consecutive_failures=2))
        assert outcome == ControlPlaneOutcome(new_state=SNOOZED, consecutive_failures=2)


class TestApplyUnsnooze(TestCase):
    @parameterized.expand(
        [
            ("snoozed", SNOOZED),
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
        ]
    )
    def test_any_state_transitions_to_not_firing_with_clean_counter(self, _name: str, state: AlertState) -> None:
        outcome = apply_unsnooze(_snapshot(state=state, consecutive_failures=1))
        assert outcome == ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)


class TestApplyThresholdChange(TestCase):
    def test_snoozed_alert_stays_snoozed(self) -> None:
        # Editing a snoozed alert's threshold must not wake it up — user explicitly asked
        # for silence.
        outcome = apply_threshold_change(_snapshot(state=SNOOZED, consecutive_failures=1))
        assert outcome == ControlPlaneOutcome(new_state=SNOOZED, consecutive_failures=1)

    @parameterized.expand(
        [
            ("not_firing", NOT_FIRING),
            ("firing", FIRING),
            ("errored", ERRORED),
            ("broken", BROKEN),
            ("pending_resolve", PENDING_RESOLVE),
        ]
    )
    def test_non_snoozed_state_resets_to_not_firing(self, _name: str, state: AlertState) -> None:
        outcome = apply_threshold_change(_snapshot(state=state, consecutive_failures=4))
        assert outcome == ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)


class TestApplyOutcome(TestCase):
    """apply_outcome is the ONLY mutator of state/consecutive_failures — covered here so
    the invariant is locked in by tests, not just convention."""

    def test_applies_control_plane_outcome(self) -> None:
        from products.logs.backend.models import LogsAlertConfiguration

        alert = LogsAlertConfiguration(
            state=FIRING.value,
            consecutive_failures=2,
            threshold_count=10,
        )
        outcome = ControlPlaneOutcome(new_state=NOT_FIRING, consecutive_failures=0)
        fields = apply_outcome(alert, outcome)
        assert alert.state == NOT_FIRING.value
        assert alert.consecutive_failures == 0
        assert fields == ["state", "consecutive_failures"]

    def test_applies_check_outcome(self) -> None:
        from products.logs.backend.models import LogsAlertConfiguration

        alert = LogsAlertConfiguration(
            state=NOT_FIRING.value,
            consecutive_failures=0,
            threshold_count=10,
        )
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
