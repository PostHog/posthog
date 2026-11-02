from uuid import UUID

from django.db import transaction

from products.logs.backend import alert_incidents
from products.logs.backend.alert_creation import AlertLimitReached, claim_alert_slot, first_check_at
from products.logs.backend.alert_state_machine import FIRING_STATES, IncidentCloseReason, IncidentEdge, incident_edge
from products.logs.backend.alert_utils import next_allowed_check_at
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.natural_language_query import (
    NaturalLanguageQueryFailed,
    NaturalLanguageQueryUnavailable,
    is_valid_date,
    translate_natural_language_query,
)
from products.logs.backend.platform_alert_backfill import logs_state_of_platform
from products.logs.backend.platform_alert_event_history import (
    MAX_MERGED_EVENT_ROWS,
    PlatformCheckRow,
    PlatformCheckRows,
    platform_check_rows,
)
from products.logs.backend.platform_source_config import ALLOWED_WINDOW_MINUTES, has_any_filter
from products.logs.backend.tasks.tasks import follow_logs_alert_task

__all__ = [
    "ALLOWED_WINDOW_MINUTES",
    "AlertLimitReached",
    "MAX_MERGED_EVENT_ROWS",
    "NaturalLanguageQueryFailed",
    "NaturalLanguageQueryUnavailable",
    "PlatformCheckRow",
    "PlatformCheckRows",
    "claim_alert_slot",
    "close_incident_before_delete",
    "close_incident_on_commit",
    "first_check_at",
    "follow_logs_alert",
    "has_any_filter",
    "is_valid_date",
    "logs_state_of_platform",
    "next_allowed_check_at",
    "platform_check_rows",
    "translate_natural_language_query",
]


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


def follow_logs_alert(*, team_id: int, alert_id: UUID) -> None:
    """Queue the copy of a logs alert that was just created or turned back on, if its team runs logs
    on the platform. The task retries a transient failure."""
    follow_logs_alert_task.delay(team_id, str(alert_id))


def close_incident_before_delete(*, team_id: int, alert_id: str, state: str) -> None:
    """Close a firing alert's incident before the delete removes the functions that deliver it.

    Best effort. The CDP consumer drops events for deleted functions, so the close often goes unsent.
    """
    if state in FIRING_STATES:
        _close_if_subscribed(team_id=team_id, alert_id=alert_id, reason=IncidentCloseReason.DELETED)
