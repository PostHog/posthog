from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, StrEnum

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


@dataclass(frozen=True)
class CheckResult:
    result_count: int | None
    threshold_breached: bool
    error_message: str | None = None
    query_duration_ms: int | None = None


@dataclass(frozen=True)
class AlertSnapshot:
    state: AlertState
    evaluation_periods: int
    datapoints_to_alarm: int
    cooldown_minutes: int
    last_notified_at: datetime | None
    snooze_until: datetime | None
    consecutive_failures: int
    recent_checks_breached: tuple[bool, ...]


@dataclass(frozen=True)
class AlertCheckOutcome:
    new_state: AlertState
    notification: NotificationAction
    consecutive_failures: int
    update_last_notified_at: bool
    error_message: str | None


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
        # Terminal until manual reset — scheduler should already be excluding these,
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
        consecutive_failures = snapshot.consecutive_failures + 1
        new_state = AlertState.BROKEN if consecutive_failures >= MAX_CONSECUTIVE_FAILURES else AlertState.ERRORED
        return AlertCheckOutcome(
            new_state=new_state,
            notification=NotificationAction.NONE,
            consecutive_failures=consecutive_failures,
            update_last_notified_at=False,
            error_message=check.error_message,
        )

    consecutive_failures = 0

    window = [check.threshold_breached, *snapshot.recent_checks_breached]
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


def _is_within_cooldown(
    last_notified_at: datetime | None,
    cooldown_minutes: int,
    now: datetime,
) -> bool:
    if cooldown_minutes <= 0 or last_notified_at is None:
        return False
    return now < last_notified_at + timedelta(minutes=cooldown_minutes)
