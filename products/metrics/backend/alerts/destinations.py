"""The event ids of a metrics alert's transitions, and the destination types it sends to.

A metrics alert's destinations are `AlertDestination` rows. Delivery maps each event id back to the
transition it announces, so it knows which rows hear it, and words the message itself.
"""

from dataclasses import replace
from typing import Final, Literal

from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationAction,
    AlertEventKind,
    DestinationType,
    EventKindSpec,
    IncidentAction,
)

METRICS_ALERT_DESTINATION_TYPES: Final = (
    DestinationType.SLACK,
    DestinationType.WEBHOOK,
    DestinationType.TEAMS,
    DestinationType.DISCORD,
    DestinationType.PAGERDUTY,
)

EventKind = Literal["firing", "resolved", "errored", "broken", "incident_opened", "incident_closed"]

_PRODUCT_LABEL = "metric alert"
_METRICS_URL = "{project.url}/metrics"
_DATA: Final[dict[str, str]] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "query": "{event.properties.query}",
    "value": "{event.properties.value}",
}

_FIRING = EventKindSpec(
    event_id="$metrics_alert_firing",
    display_kind="firing",
    header="🔴 Metric alert '{event.properties.alert_name}' is firing",
    details=(("Query", "{event.properties.query}"), ("Value", "{event.properties.value}")),
    primary_action_url=_METRICS_URL,
    primary_action_label="View in PostHog",
    webhook_body={
        "id": "{event.uuid}",
        "type": "metrics_alert.firing",
        "timestamp": "{event.properties.triggered_at}",
        "data": _DATA,
    },
    product_label=_PRODUCT_LABEL,
)

EVENT_KIND_CONFIG: Final[dict[EventKind, EventKindSpec]] = {
    "firing": _FIRING,
    "resolved": replace(
        _FIRING,
        event_id="$metrics_alert_resolved",
        display_kind="resolved",
        header="🟢 Metric alert '{event.properties.alert_name}' is resolved",
        webhook_body={**_FIRING.webhook_body, "type": "metrics_alert.resolved"},
    ),
    "errored": replace(
        _FIRING,
        event_id="$metrics_alert_errored",
        display_kind="errored",
        header="🟡 Metric alert '{event.properties.alert_name}' could not be checked",
        details=(("Reason", "{event.properties.error_message}"),),
        webhook_body={**_FIRING.webhook_body, "type": "metrics_alert.errored"},
    ),
    "broken": replace(
        _FIRING,
        event_id="$metrics_alert_broken",
        display_kind="turned off",
        header="⚠️ Metric alert '{event.properties.alert_name}' is turned off",
        details=(("Reason", "{event.properties.error_message}"),),
        webhook_body={**_FIRING.webhook_body, "type": "metrics_alert.broken"},
    ),
    # The edge kinds follow every move into and out of FIRING, whatever cooldown decided. An
    # incident manager needs a resolve for every trigger, or the incident it opened stays open.
    "incident_opened": replace(
        _FIRING,
        event_id="$metrics_alert_incident_opened",
        display_kind="incident opened",
        webhook_body={},
        additional_actions=(AlertDestinationAction(url=_METRICS_URL, label="View in PostHog"),),
        incident_action=IncidentAction.TRIGGER,
    ),
    "incident_closed": replace(
        _FIRING,
        event_id="$metrics_alert_incident_closed",
        display_kind="incident closed",
        header="Metric alert '{event.properties.alert_name}' stopped firing",
        details=(("Reason", "{event.properties.reason}"),),
        webhook_body={},
        incident_action=IncidentAction.RESOLVE,
    ),
}

# Which event id each announced kind's destinations filter on. Resolved here because the platform
# imports no source.
EVENT_IDS_BY_KIND: Final[dict[str, str]] = {
    key: spec.event_id for key, spec in EVENT_KIND_CONFIG.items() if key in set(AlertEventKind)
}

EVENT_IDS_BY_INCIDENT_ACTION: Final[dict[str, str]] = {
    spec.incident_action.value: spec.event_id for spec in EVENT_KIND_CONFIG.values() if spec.incident_action
}
