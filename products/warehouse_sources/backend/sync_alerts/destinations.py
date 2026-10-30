"""The event ids of each warehouse alert kind, and where its destinations may send.

A warehouse alert's destinations are `AlertDestination` rows on the platform, which words each
message itself. Delivery and the email recipient resolver address a transition by these event ids.

The evaluation reads Postgres rows and records no failed check, so these alerts only fire and resolve.
"""

from typing import Final

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    DestinationType,
    IncidentAction,
    SourceKind,
)

WAREHOUSE_ALERT_DESTINATION_TYPES: Final = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.TEAMS,
    DestinationType.DISCORD,
    DestinationType.PAGERDUTY,
)

# What a destination may ask to hear about. An incident manager hears every incident edge whatever it asks for.
WAREHOUSE_DESTINATION_EVENT_KINDS: Final = (AlertEventKind.FIRING, AlertEventKind.RESOLVED)

_PREFIXES: Final[dict[SourceKind, str]] = {
    SourceKind.WAREHOUSE_SOURCE: "warehouse_source_alert",
    SourceKind.WAREHOUSE_DESTINATION: "warehouse_destination_alert",
}

# Which event id each announced kind goes out under. The platform imports no source, so the
# delivery request carries this map.
EVENT_IDS_BY_KIND: Final[dict[SourceKind, dict[str, str]]] = {
    source: {kind.value: f"${prefix}_{kind.value}" for kind in WAREHOUSE_DESTINATION_EVENT_KINDS}
    for source, prefix in _PREFIXES.items()
}

# The edge kinds follow every move into and out of FIRING, whatever cooldown decided. An incident
# manager needs a resolve for every trigger, or the incident it opened stays open.
EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[SourceKind, dict[str, str]]] = {
    source: {
        IncidentAction.TRIGGER.value: f"${prefix}_incident_opened",
        IncidentAction.RESOLVE.value: f"${prefix}_incident_closed",
    }
    for source, prefix in _PREFIXES.items()
}
