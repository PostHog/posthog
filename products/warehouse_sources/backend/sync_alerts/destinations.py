"""What each warehouse alert event says, and where its destinations may send it.

A destination is a set of HogFunctions, one per event kind it handles. They are the stored form of
the destination: native delivery reads them to find who to tell and words the message itself. Nothing
emits their events, and the generic HogFunction API refuses to edit them, so their templates never run.

The evaluation reads Postgres rows and records no failed check, so these alerts only fire and resolve.
"""

from dataclasses import replace
from typing import Final, Literal

from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationAction,
    AlertEventKind,
    DestinationType,
    EventKindSpec,
    IncidentAction,
    SourceKind,
)

EventKind = Literal["firing", "resolved", "incident_opened", "incident_closed"]

WAREHOUSE_ALERT_DESTINATION_TYPES: Final = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.TEAMS,
    DestinationType.DISCORD,
    DestinationType.PAGERDUTY,
)

_SOURCES_URL = "{project.url}/data-management/sources"
_DESTINATIONS_URL = "{project.url}/data-management/warehouse-destinations"


def _event_kinds(
    *,
    prefix: str,
    product_label: str,
    headline: str,
    details: tuple[tuple[str, str], ...],
    url: str,
    data: dict[str, str],
) -> dict[EventKind, EventKindSpec]:
    firing = EventKindSpec(
        event_id=f"${prefix}_firing",
        display_kind="firing",
        header=f"🔴 {headline} '{{event.properties.alert_name}}' is firing",
        details=details,
        primary_action_url=url,
        primary_action_label="View in PostHog",
        webhook_body={
            "id": "{event.uuid}",
            "type": f"{prefix}.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": data,
        },
        product_label=product_label,
    )
    return {
        "firing": firing,
        "resolved": replace(
            firing,
            event_id=f"${prefix}_resolved",
            display_kind="resolved",
            header=f"🟢 {headline} '{{event.properties.alert_name}}' is resolved",
            webhook_body={**firing.webhook_body, "type": f"{prefix}.resolved"},
        ),
        # The edge kinds follow every move into and out of FIRING, whatever cooldown decided. An
        # incident manager needs a resolve for every trigger, or the incident it opened stays open.
        "incident_opened": replace(
            firing,
            event_id=f"${prefix}_incident_opened",
            display_kind="incident opened",
            webhook_body={},
            additional_actions=(AlertDestinationAction(url=url, label="View in PostHog"),),
            incident_action=IncidentAction.TRIGGER,
        ),
        "incident_closed": replace(
            firing,
            event_id=f"${prefix}_incident_closed",
            display_kind="incident closed",
            header=f"{headline} '{{event.properties.alert_name}}' stopped firing",
            details=(("Reason", "{event.properties.reason}"),),
            webhook_body={},
            incident_action=IncidentAction.RESOLVE,
        ),
    }


EVENT_KIND_CONFIG: Final[dict[SourceKind, dict[EventKind, EventKindSpec]]] = {
    SourceKind.WAREHOUSE_SOURCE: _event_kinds(
        prefix="warehouse_source_alert",
        product_label="warehouse sync alert",
        headline="Warehouse sync alert",
        details=(
            ("Source", "{event.properties.source}"),
            ("Tables", "{event.properties.tables}"),
            ("Error", "{event.properties.error}"),
        ),
        url=_SOURCES_URL,
        data={
            "alert_id": "{event.properties.alert_id}",
            "alert_name": "{event.properties.alert_name}",
            "source_id": "{event.properties.source_id}",
            "source": "{event.properties.source}",
            "tables": "{event.properties.tables}",
            "error": "{event.properties.error}",
        },
    ),
    SourceKind.WAREHOUSE_DESTINATION: _event_kinds(
        prefix="warehouse_destination_alert",
        product_label="warehouse destination alert",
        headline="Warehouse destination alert",
        details=(
            ("Destination", "{event.properties.destination}"),
            ("Status", "{event.properties.status}"),
            ("Error", "{event.properties.error}"),
        ),
        url=_DESTINATIONS_URL,
        data={
            "alert_id": "{event.properties.alert_id}",
            "alert_name": "{event.properties.alert_name}",
            "destination_id": "{event.properties.destination_id}",
            "destination": "{event.properties.destination}",
            "status": "{event.properties.status}",
            "error": "{event.properties.error}",
        },
    ),
}

EVENT_IDS: Final[dict[SourceKind, tuple[str, ...]]] = {
    source: tuple(spec.event_id for spec in kinds.values()) for source, kinds in EVENT_KIND_CONFIG.items()
}

# Which event id each announced kind's destinations filter on. The platform imports no source, so
# the delivery request carries this map.
EVENT_IDS_BY_KIND: Final[dict[SourceKind, dict[str, str]]] = {
    source: {
        AlertEventKind.FIRING.value: kinds["firing"].event_id,
        AlertEventKind.RESOLVED.value: kinds["resolved"].event_id,
    }
    for source, kinds in EVENT_KIND_CONFIG.items()
}

EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[SourceKind, dict[str, str]]] = {
    source: {spec.incident_action.value: spec.event_id for spec in kinds.values() if spec.incident_action}
    for source, kinds in EVENT_KIND_CONFIG.items()
}
