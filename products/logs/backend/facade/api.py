from django.db import transaction

from products.logs.backend import alert_incidents
from products.logs.backend.alert_state_machine import FIRING_STATES, IncidentCloseReason, IncidentEdge, incident_edge
from products.logs.backend.alert_utils import next_allowed_check_at
from products.logs.backend.models import LogsAlertConfiguration

__all__ = ["close_incident_before_delete", "close_incident_on_commit", "next_allowed_check_at"]


def _close_if_subscribed(*, team_id: int, alert_id: str, reason: IncidentCloseReason) -> None:
    alert = LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()
    if alert is None or not alert_incidents.has_incident_destination(alert):
        return
    alert_incidents.close_incident(alert, reason)


def close_incident_on_commit(
    *, team_id: int, alert_id: str, state_before: str, state_after: str, reason: IncidentCloseReason
) -> None:
    """Close the alert's incident after the change commits, when the change moved it out of firing."""
    if incident_edge(state_before, state_after) != IncidentEdge.CLOSED:
        return
    # Robust, so a failed close cannot turn a committed change into an error response.
    transaction.on_commit(
        lambda: _close_if_subscribed(team_id=team_id, alert_id=alert_id, reason=reason),
        robust=True,
    )


def close_incident_before_delete(*, team_id: int, alert_id: str, state: str) -> None:
    """Close a firing alert's incident before the delete removes the functions that deliver it.

    Best effort. The CDP consumer drops events for deleted functions, so the close often goes unsent.
    """
    if state in FIRING_STATES:
        _close_if_subscribed(team_id=team_id, alert_id=alert_id, reason=IncidentCloseReason.DELETED)
