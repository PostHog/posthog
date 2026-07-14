"""Build HogFunction configurations for logs alert notifications."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from products.alerts.backend.destination_configs import (
    DESTINATION_TEMPLATE_IDS,
    WEBHOOK_HEADERS,
    AlertDestinationConfig,
    DestinationType,
    EventKindSpec,
    build_alert_destination_config,
    slack_blocks,
    teams_text,
)
from products.logs.backend.models import LogsAlertConfiguration

EventKind = Literal["firing", "resolved", "broken", "errored"]
LOGS_DESTINATION_TYPES = (DestinationType.SLACK, DestinationType.WEBHOOK, DestinationType.TEAMS)


class AlertDestinationData(TypedDict):
    type: DestinationType
    slack_workspace_id: NotRequired[int]
    slack_channel_id: NotRequired[str]
    slack_channel_name: NotRequired[str]
    webhook_url: NotRequired[str]


class AlertDestinationValidationError(Exception):
    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.message = message
        self.field = field
        super().__init__(message)


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

_SLACK_CONTEXT_ELEMENTS = (
    _SEVERITY_SERVICE_CONTEXT,
    "Project: <{project.url}|{project.name}>",
)


REQUIRED_DESTINATION_FIELDS: dict[DestinationType, tuple[str, ...]] = {
    DestinationType.SLACK: ("slack_workspace_id", "slack_channel_id"),
    DestinationType.WEBHOOK: ("webhook_url",),
    DestinationType.TEAMS: ("webhook_url",),
}


def validate_destination_data(data: AlertDestinationData) -> None:
    raw_destination_type = data.get("type")
    try:
        destination_type = DestinationType(raw_destination_type)
    except (TypeError, ValueError) as error:
        choices = ", ".join(f"{choice.label} ({choice.value})" for choice in LOGS_DESTINATION_TYPES)
        raise AlertDestinationValidationError(
            f"Choose a supported destination type: {choices}.", field="type"
        ) from error

    if destination_type not in LOGS_DESTINATION_TYPES:
        choices = ", ".join(f"{choice.label} ({choice.value})" for choice in LOGS_DESTINATION_TYPES)
        raise AlertDestinationValidationError(f"Choose a supported destination type: {choices}.", field="type")

    missing_fields = tuple(field for field in REQUIRED_DESTINATION_FIELDS[destination_type] if not data.get(field))
    if len(missing_fields) == 1:
        missing_field = missing_fields[0]
        raise AlertDestinationValidationError(
            f"{missing_field} is required for {destination_type.label} destinations.", field=missing_field
        )
    if missing_fields:
        formatted_fields = " and ".join(missing_fields)
        raise AlertDestinationValidationError(f"{destination_type.label} destinations require {formatted_fields}.")


def build_destination_config(
    alert: LogsAlertConfiguration,
    kind: EventKind,
    data: AlertDestinationData,
) -> AlertDestinationConfig:
    spec = EVENT_KIND_CONFIG[kind]

    if data["type"] == DestinationType.SLACK:
        channel_display = data.get("slack_channel_name") or "channel"
        name = f"Logs alert — {alert.name} ({spec.display_kind}) → Slack #{channel_display}"
        template_id = DESTINATION_TEMPLATE_IDS[DestinationType.SLACK]
        inputs = {
            "blocks": {"value": slack_blocks(spec, _SLACK_CONTEXT_ELEMENTS)},
            "text": {"value": spec.header},
            "slack_workspace": {"value": data["slack_workspace_id"]},
            "channel": {"value": data["slack_channel_id"]},
        }
    elif data["type"] == DestinationType.WEBHOOK:
        name = f"Logs alert — {alert.name} ({spec.display_kind}) → Webhook {data['webhook_url']}"
        template_id = DESTINATION_TEMPLATE_IDS[DestinationType.WEBHOOK]
        inputs = {
            "body": {"value": spec.webhook_body},
            "url": {"value": data["webhook_url"]},
            "headers": {"value": WEBHOOK_HEADERS},
        }
    else:
        name = f"Logs alert — {alert.name} ({spec.display_kind}) → Microsoft Teams"
        template_id = DESTINATION_TEMPLATE_IDS[DestinationType.TEAMS]
        inputs = {
            "webhookUrl": {"value": data["webhook_url"]},
            "text": {"value": teams_text(spec)},
        }

    return build_alert_destination_config(
        team=alert.team,
        spec=spec,
        alert_id=str(alert.id),
        alert_name=alert.name,
        name=name,
        template_id=template_id,
        inputs=inputs,
    )
