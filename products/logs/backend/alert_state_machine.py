"""Single source of truth for LogsAlertConfiguration state transitions.

Any write to `LogsAlertConfiguration.state` or `LogsAlertConfiguration.consecutive_failures`
MUST originate here — the check-driven path goes through `evaluate_alert_check`, the
control-plane path goes through one of the `apply_*` helpers, and every caller applies
the resulting outcome via `apply_outcome`, which is the only function in the codebase
that mutates those two fields.

The semgrep rule at `.semgrep/rules/logs-alert-state-must-go-through-state-machine.yaml`
enforces this invariant in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

MAX_CONSECUTIVE_FAILURES = 5


class AlertState(StrEnum):
    NOT_FIRING = "not_firing"
    FIRING = "firing"
    PENDING_RESOLVE = "pending_resolve"
    ERRORED = "errored"
    SNOOZED = "snoozed"
    BROKEN = "broken"


class NotificationAction(Enum):
    NONE = "none"
    FIRE = "fire"
    RESOLVE = "resolve"
    ERROR = "error"
    BROKEN = "broken"


class InvalidTransition(Exception):
    """Raised by control-plane transitions when the pre-condition isn't met."""


@dataclass(frozen=True)
class CheckResult:
    result_count: int | None
    threshold_breached: bool
    error_message: str | None = None
    query_duration_ms: int | None = None
    is_transient_error: bool = False


@dataclass(frozen=True)
class AlertSnapshot:
    state: AlertState
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    last_notified_at: datetime | None
    snooze_until: datetime | None
    consecutive_failures: int
    recent_events_breached: tuple[bool, ...]


@dataclass(frozen=True)
class AlertCheckOutcome:
    new_state: AlertState
    notification: NotificationAction
    consecutive_failures: int
    update_last_notified_at: bool
    error_message: str | None


@dataclass(frozen=True)
class ControlPlaneOutcome:
    """Outcome of a user-initiated or serializer-driven transition.

    Shares `new_state` + `consecutive_failures` with `AlertCheckOutcome` so both
    can flow through `apply_outcome` uniformly.
    """

    new_state: AlertState
    consecutive_failures: int


Outcome = Union[AlertCheckOutcome, ControlPlaneOutcome]


def evaluate_alert_check(
    snapshot: AlertSnapshot,
    check: CheckResult,
    now: datetime,
) -> AlertCheckOutcome:
    """Implements the RFC state table: N-of-M sliding-window trigger
    (CloudWatch-style) for firing, immediate resolution on the first OK
    check, and cooldown suppression.
    """
    if snapshot.state == AlertState.BROKEN:
        # Terminal until a user reset — the scheduler already excludes BROKEN alerts,
        # this is belt-and-braces against a race.
        return AlertCheckOutcome(
            new_state=AlertState.BROKEN,
            notification=NotificationAction.NONE,
            consecutive_failures=snapshot.consecutive_failures,
            update_last_notified_at=False,
            error_message=None,
        )

    if snapshot.state == AlertState.SNOOZED:
        if snapshot.snooze_until is not None and snapshot.snooze_until > now:
            return AlertCheckOutcome(
                new_state=AlertState.SNOOZED,
                notification=NotificationAction.NONE,
                consecutive_failures=snapshot.consecutive_failures,
                update_last_notified_at=False,
                error_message=None,
            )
        effective_state = AlertState.NOT_FIRING
    else:
        effective_state = snapshot.state

    if check.error_message is not None:
        consecutive_failures = (
            snapshot.consecutive_failures if check.is_transient_error else snapshot.consecutive_failures + 1
        )
        new_state = AlertState.BROKEN if consecutive_failures >= MAX_CONSECUTIVE_FAILURES else AlertState.ERRORED
        first_error = (
            effective_state != AlertState.ERRORED
            and snapshot.state != AlertState.ERRORED  # prevents re-notification after snooze auto-expiry
            and new_state == AlertState.ERRORED
        )
        first_broken = new_state == AlertState.BROKEN
        if first_broken:
            notification = NotificationAction.BROKEN
        elif first_error:
            notification = NotificationAction.ERROR
        else:
            notification = NotificationAction.NONE
        return AlertCheckOutcome(
            new_state=new_state,
            notification=notification,
            consecutive_failures=consecutive_failures,
            update_last_notified_at=False,
            error_message=check.error_message,
        )

    consecutive_failures = 0

    window = [check.threshold_breached, *snapshot.recent_events_breached]
    m = snapshot.evaluation_periods
    window = window[:m]

    breach_count = sum(1 for b in window if b)
    n = snapshot.datapoints_to_alarm

    if effective_state == AlertState.ERRORED:
        effective_state = AlertState.NOT_FIRING

    notification = NotificationAction.NONE

    if effective_state == AlertState.NOT_FIRING:
        if breach_count >= n:
            new_state = AlertState.FIRING
            notification = NotificationAction.FIRE
        else:
            new_state = AlertState.NOT_FIRING

    # PENDING_RESOLVE is currently unused — resolution is immediate on the first
    # OK check. Kept in the enum for future symmetric N-of-M resolution support.
    elif effective_state in (AlertState.FIRING, AlertState.PENDING_RESOLVE):
        if check.threshold_breached:
            new_state = AlertState.FIRING
        else:
            # Always resolve after a single OK check — N-of-M only governs firing
            new_state = AlertState.NOT_FIRING
            notification = NotificationAction.RESOLVE

    else:
        new_state = AlertState.NOT_FIRING

    update_last_notified_at = False
    if notification != NotificationAction.NONE:
        if _is_within_cooldown(snapshot.last_notified_at, snapshot.cooldown_minutes, now):
            notification = NotificationAction.NONE
        else:
            update_last_notified_at = True

    return AlertCheckOutcome(
        new_state=new_state,
        notification=notification,
        consecutive_failures=consecutive_failures,
        update_last_notified_at=update_last_notified_at,
        error_message=None,
    )


def apply_user_reset(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    if snapshot.state != AlertState.BROKEN:
        raise InvalidTransition(f"Only broken alerts can be reset. Current state is {snapshot.state.value}.")
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_disable(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    # Preserve consecutive_failures so re-enable without reset doesn't silently
    # wipe forensic state.
    return ControlPlaneOutcome(
        new_state=AlertState.NOT_FIRING,
        consecutive_failures=snapshot.consecutive_failures,
    )


def apply_enable(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_snooze(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(
        new_state=AlertState.SNOOZED,
        consecutive_failures=snapshot.consecutive_failures,
    )


def apply_unsnooze(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_threshold_change(snapshot: AlertSnapshot) -> ControlPlaneOutcome:
    # Snoozed alerts stay snoozed on edit — editing configuration must not wake a
    # silenced alert.
    if snapshot.state == AlertState.SNOOZED:
        return ControlPlaneOutcome(
            new_state=AlertState.SNOOZED,
            consecutive_failures=snapshot.consecutive_failures,
        )
    return ControlPlaneOutcome(new_state=AlertState.NOT_FIRING, consecutive_failures=0)


def apply_outcome(
    alert: LogsAlertConfiguration,
    outcome: Outcome,
    *,
    kind: LogsAlertEvent.Kind | None = None,
) -> list[str]:
    """Mutates `alert.state` and `alert.consecutive_failures` from an outcome.
    Returns modified field names for `save(update_fields=...)`.

    If `kind` is provided, writes a `LogsAlertEvent` audit row — even when
    state_before == state_after, because the caller has already decided the action
    is audit-worthy (e.g. enabling an already-NOT_FIRING alert). Worker CHECK rows
    are written by the temporal activity, not here.
    """
    state_before = alert.state
    alert.state = outcome.new_state.value
    alert.consecutive_failures = outcome.consecutive_failures

    if kind is not None:
        from products.logs.backend.models import LogsAlertEvent

        LogsAlertEvent.objects.create(
            alert=alert,
            kind=kind,
            threshold_breached=False,
            state_before=state_before,
            state_after=outcome.new_state.value,
        )

    return ["state", "consecutive_failures"]


def _is_within_cooldown(
    last_notified_at: datetime | None,
    cooldown_minutes: int,
    now: datetime,
) -> bool:
    if cooldown_minutes <= 0 or last_notified_at is None:
        return False
    return now < last_notified_at + timedelta(minutes=cooldown_minutes)
