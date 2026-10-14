from __future__ import annotations

import dataclasses
from typing import Literal

from django.conf import settings

import structlog

from posthog.models import Team

from products.logs.backend.alert_state_machine import NotificationAction
from products.logs.backend.models import LogsAlertConfiguration
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

SOURCE_PRODUCT = "logs"
SOURCE_TYPE = "alert_state_change"

AlertSignalAction = Literal["firing", "broken"]

# Notification -> (action label, weight). Only FIRE and BROKEN are signalled —
# both are investigate-now (weight 1.0). RESOLVE (rarely worth investigating) and
# ERROR (transient — the real signal is the eventual BROKEN auto-disable) are
# intentionally absent, so signal_action_and_weight returns None for them.
_ACTION_WEIGHT: dict[NotificationAction, tuple[AlertSignalAction, float]] = {
    NotificationAction.FIRE: ("firing", 1.0),
    NotificationAction.BROKEN: ("broken", 1.0),
}


@dataclasses.dataclass(frozen=True)
class NotifiedAlert:
    """Serialisable descriptor of one alert that emitted a notification this cycle.

    Crosses the Temporal activity boundary, so every field is a primitive / JSON.
    """

    alert_id: str
    team_id: int
    alert_name: str
    action: AlertSignalAction
    weight: float
    threshold_count: int
    threshold_operator: str
    window_minutes: int
    result_count: int | None
    consecutive_failures: int
    filters: dict
    # Set by a caller that retries, so a repeated emission starts no second signal.
    idempotency_key: str | None = None


_WEIGHT_BY_ACTION: dict[AlertSignalAction, float] = dict(_ACTION_WEIGHT.values())


@dataclasses.dataclass(frozen=True)
class PlatformAlertSignal:
    """One alert the platform announced as firing or auto-disabled, for which logs emits a signal.

    Crosses the Temporal activity boundary, so every field is a primitive.
    """

    alert_id: str
    action: AlertSignalAction
    result_count: int | None
    consecutive_failures: int
    evaluation_key: str


def signal_action_and_weight(notification: NotificationAction) -> tuple[AlertSignalAction, float] | None:
    """Map a NotificationAction to (action label, weight), or None if not signalable."""
    return _ACTION_WEIGHT.get(notification)


def _alert_url(team_id: int) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/logs"


def build_signal_extra(na: NotifiedAlert) -> dict:
    return {
        "alert_id": na.alert_id,
        "alert_name": na.alert_name,
        "action": na.action,
        "threshold_count": na.threshold_count,
        "threshold_operator": na.threshold_operator,
        "window_minutes": na.window_minutes,
        "result_count": na.result_count,
        "consecutive_failures": na.consecutive_failures,
        "filters": na.filters,
        "url": _alert_url(na.team_id),
    }


def build_signal_description(na: NotifiedAlert) -> str:
    services = na.filters.get("serviceNames", [])
    severities = na.filters.get("severityLevels", [])
    scope = ""
    if services:
        scope += f" Services: {', '.join(services)}."
    if severities:
        scope += f" Severities: {', '.join(severities)}."

    if na.action == "firing":
        return (
            f'Logs alert "{na.alert_name}" is firing: log count went {na.threshold_operator} '
            f"the threshold of {na.threshold_count} over a {na.window_minutes}m window "
            f"(observed {na.result_count}).{scope}"
        )
    return (
        f'Logs alert "{na.alert_name}" was auto-disabled (broken) after '
        f"{na.consecutive_failures} consecutive failed checks.{scope}"
    )


async def emit_alert_state_change_signal(team: Team, na: NotifiedAlert) -> bool:
    """Emit one logs-alert signal. Returns True on success. Never raises."""
    description = build_signal_description(na)
    extra = build_signal_extra(na)

    source_id = f"{na.alert_id}:{na.action}"
    try:
        await emit_signal(
            team=team,
            source_product=SOURCE_PRODUCT,
            source_type=SOURCE_TYPE,
            source_id=source_id,
            description=description,
            weight=na.weight,
            extra=extra,
            idempotency_key=na.idempotency_key,
        )
        return True
    except Exception:
        logger.exception("Failed to emit logs alert signal", alert_id=na.alert_id, action=na.action)
        return False


def notified_alerts_for_platform(team_id: int, signals: list[PlatformAlertSignal]) -> list[NotifiedAlert]:
    """The signal facts for alerts the platform announced, read from their logs alert rows.

    An alert whose logs row is gone gets no signal, the way the logs stack sends none for it.
    """
    alerts = {
        str(alert.id): alert
        for alert in LogsAlertConfiguration.objects.filter(team_id=team_id, id__in=[s.alert_id for s in signals])
    }
    notified: list[NotifiedAlert] = []
    for signal in signals:
        alert = alerts.get(signal.alert_id)
        if alert is None:
            continue
        notified.append(
            NotifiedAlert(
                alert_id=signal.alert_id,
                team_id=team_id,
                alert_name=alert.name,
                action=signal.action,
                weight=_WEIGHT_BY_ACTION[signal.action],
                threshold_count=alert.threshold_count,
                threshold_operator=alert.threshold_operator,
                window_minutes=alert.window_minutes,
                result_count=signal.result_count,
                consecutive_failures=signal.consecutive_failures,
                filters=alert.filters,
                idempotency_key=f"{signal.alert_id}:{signal.action}:{signal.evaluation_key}",
            )
        )
    return notified
