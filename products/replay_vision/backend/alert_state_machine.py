"""Single source of truth for VisionAlertConfiguration state transitions.

Any write to `VisionAlertConfiguration.state` or `.consecutive_failures` MUST originate
here — the check-driven path goes through `evaluate_alert_check`, the control-plane path
goes through one of the shared `apply_*` helpers, and every caller applies the resulting
outcome via `apply_outcome`, the only function that mutates those two fields. The semgrep
rule at `.semgrep/rules/security/alert-state-must-go-through-state-machine.yaml` enforces
this in CI.

The decision logic lives in `products/alerts/backend/state_machine.py`, configured with
`VISION_ALERT_POLICY`; this module owns the vision-shaped inputs and the model mutation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from posthog.dataclasses import frozen

from products.alerts.backend.state_machine import (
    MAX_CONSECUTIVE_FAILURES,
    AlertCheckOutcome,
    AlertPolicy,
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
    from products.replay_vision.backend.models.vision_alert import VisionAlertConfiguration, VisionAlertEvent

__all__ = [
    "MAX_CONSECUTIVE_FAILURES",
    "VISION_ALERT_POLICY",
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

# Deliberately the shared defaults (same semantics as logs): fire on transition only,
# resolve notifications on, BROKEN terminal until user reset. Diverge by setting fields
# here, never by forking the shared machine.
VISION_ALERT_POLICY = AlertPolicy()


@frozen
class CheckResult:
    metric_value: float | None
    threshold_breached: bool
    error_message: str | None = None
    is_inconclusive: bool = False
    is_transient_error: bool = False


@frozen
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
            is_inconclusive=check.is_inconclusive,
            is_transient_error=check.is_transient_error,
        ),
        now,
        policy=VISION_ALERT_POLICY,
    )


def apply_outcome(
    alert: VisionAlertConfiguration,
    outcome: Outcome,
    *,
    kind: VisionAlertEvent.Kind | None = None,
) -> list[str]:
    """Mutates `alert.state` and `alert.consecutive_failures` from an outcome.
    Returns modified field names for `save(update_fields=...)`.

    If `kind` is provided, writes a `VisionAlertEvent` audit row — even when
    state_before == state_after, because the caller has already decided the action is
    audit-worthy. Worker CHECK rows are written by the temporal activity, not here.
    """
    state_before = alert.state
    alert.state = outcome.new_state.value
    alert.consecutive_failures = outcome.consecutive_failures

    if kind is not None:
        from products.replay_vision.backend.models.vision_alert import VisionAlertEvent

        VisionAlertEvent.objects.create(
            alert=alert,
            kind=kind,
            threshold_breached=False,
            state_before=state_before,
            state_after=outcome.new_state.value,
        )

    return ["state", "consecutive_failures"]
