"""Build HogFunction configurations for metrics alert notifications."""

from __future__ import annotations

from typing import Literal

from products.alerts.backend.destination_configs import DestinationType, EventKindSpec

EventKind = Literal["firing", "resolved", "broken", "errored"]
METRICS_DESTINATION_TYPES = (DestinationType.SLACK, DestinationType.WEBHOOK, DestinationType.TEAMS)

METRICS_ALERT_EVENT_IDS = (
    "$metrics_alert_firing",
    "$metrics_alert_resolved",
    "$metrics_alert_auto_disabled",
    "$metrics_alert_errored",
)

_PRODUCT_LABEL = "metric alert"
_FIRE_RESOLVE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "metric_name": "{event.properties.metric_name}",
    "value": "{event.properties.value}",
    "threshold_value": "{event.properties.threshold_value}",
    "threshold_operator": "{event.properties.threshold_operator}",
    "window_minutes": "{event.properties.window_minutes}",
    "labels": "{event.properties.labels}",
    "alert_url": "{project.url}/metrics/alerts/{event.properties.alert_id}",
}

_BROKEN_ERRORED_BASE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "metric_name": "{event.properties.metric_name}",
    "consecutive_failures": "{event.properties.consecutive_failures}",
    "alert_url": "{project.url}/metrics/alerts/{event.properties.alert_id}",
}


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": EventKindSpec(
        event_id="$metrics_alert_firing",
        display_kind="firing",
        header="🔴 Metric alert '{event.properties.alert_name}' is firing",
        details=(
            (
                "Threshold breached",
                "{event.properties.metric_name} = {event.properties.value} "
                "({event.properties.threshold_operator} {event.properties.threshold_value}) "
                "over {event.properties.window_minutes}m",
            ),
            ("Labels", "{event.properties.labels}"),
        ),
        primary_action_url="{project.url}/metrics/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "metrics_alert.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "resolved": EventKindSpec(
        event_id="$metrics_alert_resolved",
        display_kind="resolved",
        header="🟢 Metric alert '{event.properties.alert_name}' has resolved",
        details=(
            (
                "Current value",
                "{event.properties.metric_name} = {event.properties.value} "
                "({event.properties.threshold_operator} {event.properties.threshold_value}) "
                "over {event.properties.window_minutes}m",
            ),
        ),
        primary_action_url="{project.url}/metrics/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "metrics_alert.resolved",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "broken": EventKindSpec(
        event_id="$metrics_alert_auto_disabled",
        display_kind="auto-disabled",
        header="⚠️ Metric alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.last_error_message}"),
        ),
        primary_action_url="{project.url}/metrics/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "metrics_alert.auto_disabled",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "last_error_message": "{event.properties.last_error_message}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
    "errored": EventKindSpec(
        event_id="$metrics_alert_errored",
        display_kind="errored",
        header="🟡 Metric alert '{event.properties.alert_name}' couldn't evaluate",
        details=(
            ("Reason", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        primary_action_url="{project.url}/metrics/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "metrics_alert.errored",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "error_message": "{event.properties.error_message}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
}

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG.keys())

METRICS_ALERT_SLACK_CONTEXT_ELEMENTS = (
    "Metric: {event.properties.metric_name}",
    "Project: <{project.url}|{project.name}>",
)
