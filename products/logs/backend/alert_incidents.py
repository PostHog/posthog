"""Incident events for destinations that hold an incident open, such as PagerDuty."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from products.alerts.backend.facade.destinations import (
    alert_internal_event_delivered,
    configured_destination_template_ids,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.logs.backend.alert_destinations import LOGS_ALERT_INCIDENT_CLOSED_EVENT, LOGS_ALERT_INCIDENT_OPENED_EVENT
from products.logs.backend.alert_state_machine import IncidentCloseReason

if TYPE_CHECKING:
    from products.logs.backend.models import LogsAlertConfiguration


def has_incident_destination(alert: LogsAlertConfiguration) -> bool:
    """Whether a destination of this alert follows the incident kinds.

    An alert without one sends no incident events, so a lost incident event can never roll back a
    notification its Slack, Teams or webhook destinations already received.
    """
    return bool(
        configured_destination_template_ids(
            team_id=alert.team_id,
            alert_id=str(alert.id),
            allowed_event_ids=(LOGS_ALERT_INCIDENT_OPENED_EVENT, LOGS_ALERT_INCIDENT_CLOSED_EVENT),
        )
    )


def incident_closed_properties(
    alert: LogsAlertConfiguration, reason: IncidentCloseReason, now: datetime
) -> dict[str, Any]:
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        "team_id": alert.team_id,
        "reason": reason.value,
        "triggered_at": now.isoformat(),
    }


def close_incident(
    alert: LogsAlertConfiguration, reason: IncidentCloseReason, *, flush_timeout_seconds: float | None = None
) -> bool:
    """Send the close for an alert leaving firing, and return whether it was handed off.

    With `flush_timeout_seconds`, the return value says the broker took the close, and a lost close
    also shows in the delivery failure metric and log. Without it, the return value only says the
    close was queued. A web request passes none, because the flush waits on the process-wide producer.
    """
    now = datetime.now(UTC)
    produce_result = produce_alert_internal_event(
        team_id=alert.team_id,
        event_name=LOGS_ALERT_INCIDENT_CLOSED_EVENT,
        properties=incident_closed_properties(alert, reason, now),
        timestamp=now,
    )
    if produce_result is None:
        return False
    if flush_timeout_seconds is None:
        return True
    flush_alert_internal_events(flush_timeout_seconds)
    return alert_internal_event_delivered(
        produce_result,
        team_id=alert.team_id,
        alert_id=str(alert.id),
        event_name=LOGS_ALERT_INCIDENT_CLOSED_EVENT,
    )
