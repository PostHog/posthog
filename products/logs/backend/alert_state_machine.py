"""Single source of truth for LogsAlertConfiguration state transitions.

Any write to `LogsAlertConfiguration.state` or `LogsAlertConfiguration.consecutive_failures`
MUST originate here — the check-driven path goes through `evaluate_alert_check`, the
control-plane path goes through one of the `apply_*` helpers, and every caller applies
the resulting outcome via `apply_outcome`, which is the only function in the codebase
that mutates those two fields.

The semgrep rule at `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml`
enforces this invariant in CI.

The decision logic itself lives in the shared machine at `common/alerting/state_machine.py`
(configured here with `LOGS_ALERT_POLICY`); this module owns the logs-shaped inputs
(`AlertSnapshot`, `CheckResult`) and the model mutation (`apply_outcome`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from common.alerting.state_machine import (
    LOGS_ALERT_POLICY,
    MAX_CONSECUTIVE_FAILURES,
    AlertCheckOutcome,
    AlertSnapshot as SharedAlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    InvalidTransition,
    NotificationAction,
    Outcome,
    apply_disable,
    apply_enable,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
    evaluate_alert_check as shared_evaluate_alert_check,
)

if TYPE_CHECKING:
    from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

__all__ = [
    "MAX_CONSECUTIVE_FAILURES",
    "AlertCheckOutcome",
    "AlertSnapshot",
    "AlertState",
    "CheckResult",
    "ControlPlaneOutcome",
    "InvalidTransition",
    "NotificationAction",
    "Outcome",
    "apply_disable",
    "apply_enable",
    "apply_outcome",
    "apply_snooze",
    "apply_threshold_change",
    "apply_unsnooze",
    "apply_user_reset",
    "evaluate_alert_check",
]


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


def evaluate_alert_check(
    snapshot: AlertSnapshot,
    check: CheckResult,
    now: datetime,
) -> AlertCheckOutcome:
    """Implements the RFC state table: N-of-M sliding-window trigger
    (CloudWatch-style) for firing, immediate resolution on the first OK
    check, and cooldown suppression.
    """
    # Honor an active snooze regardless of persisted state (except BROKEN, which
    # is terminal). The worker loads alerts at batch start and bulk-saves minutes
    # later, so its stale non-SNOOZED state can clobber a concurrent user snooze;
    # snooze_until survives (it's not in the worker's field list) and unsnooze
    # nulls it, so a future value always means "user snoozed". Returning SNOOZED
    # silences the alert and repairs the clobbered row next cycle. The shared
    # machine deliberately ignores a stray snooze_until on a non-SNOOZED alert, so
    # this repair lives here — alongside the logs worker that causes the clobber.
    if snapshot.state != AlertState.BROKEN and snapshot.snooze_until is not None and snapshot.snooze_until > now:
        return AlertCheckOutcome(
            new_state=AlertState.SNOOZED,
            notification=NotificationAction.NONE,
            consecutive_failures=snapshot.consecutive_failures,
            update_last_notified_at=False,
            error_message=None,
        )

    return shared_evaluate_alert_check(
        SharedAlertSnapshot(
            state=snapshot.state,
            cooldown=timedelta(minutes=snapshot.cooldown_minutes),
            last_notified_at=snapshot.last_notified_at,
            snooze_until=snapshot.snooze_until,
            consecutive_failures=snapshot.consecutive_failures,
            evaluation_periods=snapshot.evaluation_periods,
            datapoints_to_alarm=snapshot.datapoints_to_alarm,
            recent_events_breached=snapshot.recent_events_breached,
        ),
        CheckInput(
            threshold_breached=check.threshold_breached,
            error_message=check.error_message,
            is_transient_error=check.is_transient_error,
        ),
        now,
        policy=LOGS_ALERT_POLICY,
    )


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
