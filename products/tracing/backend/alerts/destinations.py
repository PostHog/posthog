"""The event ids of a traces alert's transitions.

A traces alert's destinations are `AlertDestination` rows. Delivery maps each event id back to the
transition it announces, so it knows which rows hear it, and words the message itself.
"""

from typing import Final

from products.alerts_platform.backend.facade.contracts import AlertEventKind, IncidentAction

# The event id each announced kind travels under. Resolved here because the platform imports no source.
EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    AlertEventKind.FIRING.value: "$traces_alert_firing",
    AlertEventKind.RESOLVED.value: "$traces_alert_resolved",
    AlertEventKind.ERRORED.value: "$traces_alert_errored",
    AlertEventKind.BROKEN.value: "$traces_alert_broken",
}

# The event id each incident action travels under. An incident follows every move into and out of
# FIRING, whatever cooldown decided, so an incident manager gets a resolve for every trigger.
EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[str, str]] = {
    IncidentAction.TRIGGER.value: "$traces_alert_incident_opened",
    IncidentAction.RESOLVE.value: "$traces_alert_incident_closed",
}
