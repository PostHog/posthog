"""Build HogFunction configurations for logs alert notifications."""

from __future__ import annotations

from typing import Literal

from products.alerts.backend.destination_configs import DestinationType, EventKindSpec

EventKind = Literal["firing", "resolved", "broken", "errored"]
LOGS_DESTINATION_TYPES = (DestinationType.SLACK, DestinationType.WEBHOOK, DestinationType.TEAMS)


_PRODUCT_LABEL = "logs alert"
_FIRE_RESOLVE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "result_count": "{event.properties.result_count}",
    "threshold_count": "{event.properties.threshold_count}",
    "threshold_operator": "{event.properties.threshold_operator}",
    "window_minutes": "{event.properties.window_minutes}",
    "service_names": "{event.properties.service_names}",
    "severity_levels": "{event.properties.severity_levels}",
    "logs_url": "{project.url}/logs?{event.properties.logs_url_params}",
    "alert_url": "{project.url}/logs/alerts/{event.properties.alert_id}",
}

_BROKEN_ERRORED_BASE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "consecutive_failures": "{event.properties.consecutive_failures}",
    "service_names": "{event.properties.service_names}",
    "severity_levels": "{event.properties.severity_levels}",
    "alert_url": "{project.url}/logs/alerts/{event.properties.alert_id}",
}


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": EventKindSpec(
        event_id="$logs_alert_firing",
        display_kind="firing",
        header="🔴 Log alert '{event.properties.alert_name}' is firing",
        details=(
            (
                "Threshold breached",
                "{event.properties.result_count} logs in {event.properties.window_minutes}m "
                "(threshold: {event.properties.threshold_operator} {event.properties.threshold_count})",
            ),
        ),
        primary_action_url="{project.url}/logs?{event.properties.logs_url_params}",
        primary_action_label="View logs",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "resolved": EventKindSpec(
        event_id="$logs_alert_resolved",
        display_kind="resolved",
        header="🟢 Log alert '{event.properties.alert_name}' has resolved",
        details=(
            (
                "Current count",
                "{event.properties.result_count} logs in {event.properties.window_minutes}m "
                "(threshold: {event.properties.threshold_operator} {event.properties.threshold_count})",
            ),
        ),
        primary_action_url="{project.url}/logs?{event.properties.logs_url_params}",
        primary_action_label="View logs",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.resolved",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "broken": EventKindSpec(
        event_id="$logs_alert_auto_disabled",
        display_kind="auto-disabled",
        header="⚠️ Log alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.last_error_message}"),
        ),
        primary_action_url="{project.url}/logs/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.auto_disabled",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "last_error_message": "{event.properties.last_error_message}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
    "errored": EventKindSpec(
        event_id="$logs_alert_errored",
        display_kind="errored",
        header="🟡 Log alert '{event.properties.alert_name}' couldn't evaluate",
        details=(
            ("Reason", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        primary_action_url="{project.url}/logs/alerts/{event.properties.alert_id}",
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.errored",
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

_SEVERITY_SERVICE_CONTEXT = (
    "{if(length(event.properties.severity_levels) > 0 or length(event.properties.service_names) > 0,"
    " concat("
    "  if(length(event.properties.severity_levels) > 0,"
    "    concat('Severity: ', arrayStringConcat(event.properties.severity_levels, ', ')),"
    "    ''),"
    "  if(length(event.properties.severity_levels) > 0 and length(event.properties.service_names) > 0,"
    "    ' | ', ''),"
    "  if(length(event.properties.service_names) > 0,"
    "    concat('Services: ', arrayStringConcat(event.properties.service_names, ', ')),"
    "    '')"
    " ),"
    " 'All log levels and services')}"
)

LOGS_ALERT_SLACK_CONTEXT_ELEMENTS = (
    _SEVERITY_SERVICE_CONTEXT,
    "Project: <{project.url}|{project.name}>",
)
