"""The event ids of a metrics alert's transitions, and the destination types it sends to.

A metrics alert's destinations are `AlertDestination` rows. Delivery maps each event id back to the
transition it announces, so it knows which rows hear it, and words the message itself.
"""

from typing import Final

from products.alerts_platform.backend.facade.contracts import AlertEventKind, DestinationType, IncidentAction

METRICS_ALERT_DESTINATION_TYPES: Final = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.TEAMS,
    DestinationType.DISCORD,
    DestinationType.PAGERDUTY,
)

# The event id each announced kind travels under. Resolved here because the platform imports no source.
EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    AlertEventKind.FIRING.value: "$metrics_alert_firing",
    AlertEventKind.RESOLVED.value: "$metrics_alert_resolved",
    AlertEventKind.ERRORED.value: "$metrics_alert_errored",
    AlertEventKind.BROKEN.value: "$metrics_alert_broken",
}

# The event id each incident action travels under. An incident follows every move into and out of
# FIRING, whatever cooldown decided, so an incident manager gets a resolve for every trigger.
EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[str, str]] = {
    IncidentAction.TRIGGER.value: "$metrics_alert_incident_opened",
    IncidentAction.RESOLVE.value: "$metrics_alert_incident_closed",
}
