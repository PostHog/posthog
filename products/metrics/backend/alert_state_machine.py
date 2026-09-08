"""Single source of truth for MetricsAlertConfiguration state transitions.

Any write to `MetricsAlertConfiguration.state` or
`MetricsAlertConfiguration.consecutive_failures` MUST originate here — the
check-driven path goes through `evaluate_alert_check`, the control-plane path goes
through the shared `apply_*` helpers, and every caller applies the resulting outcome
via `apply_outcome`, the only function in this product that mutates those two fields.

The decision logic lives in `products/alerts/backend/state_machine.py` (configured
here with `LOGS_ALERT_POLICY`: metrics shares logs' lifecycle semantics — N-of-M
sliding-window firing, immediate resolve on the first OK check, cooldown suppression,
terminal BROKEN). This module owns the metrics-shaped inputs (`AlertSnapshot`,
`CheckResult`) and the model mutation (`apply_outcome`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from products.alerts.backend.state_machine import (
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
    from products.metrics.backend.models import MetricsAlertConfiguration, MetricsAlertEvent

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
    # The latest evaluated value (None when the check errored or no data).
    value: float | None
    threshold_breached: bool
    # Labels of the breaching group when group_by is set ({} for the un-grouped alert).
    labels: dict = field(default_factory=dict)
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
    """N-of-M sliding-window trigger (CloudWatch-style) for firing, immediate
    resolution on the first OK check, and cooldown suppression."""
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
    alert: MetricsAlertConfiguration,
    outcome: Outcome,
    *,
    kind: MetricsAlertEvent.Kind | None = None,
) -> list[str]:
    """Mutates `alert.state` and `alert.consecutive_failures` from an outcome.
    Returns modified field names for `save(update_fields=...)`.

    If `kind` is provided, writes a `MetricsAlertEvent` audit row. Worker CHECK rows
    are written by the temporal activity, not here.
    """
    state_before = alert.state
    alert.state = outcome.new_state.value
    alert.consecutive_failures = outcome.consecutive_failures

    if kind is not None:
        from products.metrics.backend.models import MetricsAlertEvent  # noqa: PLC0415

        MetricsAlertEvent.objects.create(
            alert=alert,
            kind=kind,
            threshold_breached=False,
            state_before=state_before,
            state_after=outcome.new_state.value,
        )

    return ["state", "consecutive_failures"]
