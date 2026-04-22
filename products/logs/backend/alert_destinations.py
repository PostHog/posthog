"""Build HogFunction configurations for logs alert notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from products.logs.backend.models import LogsAlertConfiguration

EventKind = Literal["firing", "resolved", "broken"]


@dataclass(frozen=True)
class EventKindSpec:
    event_id: str
    header: str
    body: str
    button_url: str
    button_label: str
    webhook_body: dict[str, str]


_FIRE_RESOLVE_WEBHOOK_BODY: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "result_count": "{event.properties.result_count}",
    "threshold_count": "{event.properties.threshold_count}",
    "threshold_operator": "{event.properties.threshold_operator}",
    "window_minutes": "{event.properties.window_minutes}",
    "service_names": "{event.properties.service_names}",
    "severity_levels": "{event.properties.severity_levels}",
    "logs_url": "{project.url}/logs?{event.properties.logs_url_params}",
    "triggered_at": "{event.properties.triggered_at}",
}


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": EventKindSpec(
        event_id="$logs_alert_firing",
        header="🔴 Log alert '{event.properties.alert_name}' is firing",
        body=(
            "*Threshold breached:* {event.properties.result_count} logs in "
            "{event.properties.window_minutes}m "
            "(threshold: {event.properties.threshold_operator} {event.properties.threshold_count})"
        ),
        button_url="{project.url}/logs?{event.properties.logs_url_params}",
        button_label="View logs",
        webhook_body={"event": "firing", **_FIRE_RESOLVE_WEBHOOK_BODY},
    ),
    "resolved": EventKindSpec(
        event_id="$logs_alert_resolved",
        header="🟢 Log alert '{event.properties.alert_name}' has resolved",
        body=(
            "*Current count:* {event.properties.result_count} logs in "
            "{event.properties.window_minutes}m "
            "(threshold: {event.properties.threshold_operator} {event.properties.threshold_count})"
        ),
        button_url="{project.url}/logs?{event.properties.logs_url_params}",
        button_label="View logs",
        webhook_body={"event": "resolved", **_FIRE_RESOLVE_WEBHOOK_BODY},
    ),
    "broken": EventKindSpec(
        event_id="$logs_alert_auto_disabled",
        header="⚠️ Log alert '{event.properties.alert_name}' was auto-disabled",
        body=(
            "*Reason:* {event.properties.consecutive_failures} consecutive check failures.\n"
            "*Last error:* {event.properties.last_error_message}"
        ),
        # Deep-link to the alert modal (via the ?alertId= param handled in logsSceneLogic) —
        # a broken alert's viewer URL would show zero logs because the alert is no longer checking.
        button_url="{project.url}/logs?alertId={event.properties.alert_id}",
        button_label="View alert",
        webhook_body={
            "event": "broken",
            "alert_id": "{event.properties.alert_id}",
            "alert_name": "{event.properties.alert_name}",
            "consecutive_failures": "{event.properties.consecutive_failures}",
            "last_error_message": "{event.properties.last_error_message}",
            "service_names": "{event.properties.service_names}",
            "severity_levels": "{event.properties.severity_levels}",
            "alert_url": "{project.url}/logs?alertId={event.properties.alert_id}",
            "triggered_at": "{event.properties.triggered_at}",
        },
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


def _slack_blocks(spec: EventKindSpec) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": spec.header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": spec.body}},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": _SEVERITY_SERVICE_CONTEXT},
                {"type": "mrkdwn", "text": "Project: <{project.url}|{project.name}>"},
            ],
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "url": spec.button_url,
                    "text": {"text": spec.button_label, "type": "plain_text"},
                    "type": "button",
                }
            ],
        },
    ]


def _filter_for(alert: LogsAlertConfiguration, kind: EventKind) -> dict[str, Any]:
    return {
        "events": [{"id": EVENT_KIND_CONFIG[kind].event_id, "type": "events"}],
        "properties": [
            {
                "key": "alert_id",
                "value": str(alert.id),
                "operator": "exact",
                "type": "event",
            }
        ],
    }


def build_slack_config(
    alert: LogsAlertConfiguration,
    kind: EventKind,
    slack_workspace_id: int,
    slack_channel_id: str,
    slack_channel_name: str | None,
) -> dict[str, Any]:
    spec = EVENT_KIND_CONFIG[kind]
    channel_display = slack_channel_name or "channel"
    return {
        "team": alert.team,
        "type": "internal_destination",
        "enabled": True,
        "filters": _filter_for(alert, kind),
        "name": f"{alert.name}: {kind} → Slack #{channel_display}",
        "template_id": "template-slack",
        "inputs": {
            "blocks": {"value": _slack_blocks(spec)},
            "text": {"value": spec.header},
            "slack_workspace": {"value": slack_workspace_id},
            "channel": {"value": slack_channel_id},
        },
    }


def build_webhook_config(
    alert: LogsAlertConfiguration,
    kind: EventKind,
    webhook_url: str,
) -> dict[str, Any]:
    spec = EVENT_KIND_CONFIG[kind]
    return {
        "team": alert.team,
        "type": "internal_destination",
        "enabled": True,
        "filters": _filter_for(alert, kind),
        "name": f"{alert.name}: {kind} → Webhook {webhook_url}",
        "template_id": "template-webhook",
        "inputs": {
            "body": {"value": spec.webhook_body},
            "url": {"value": webhook_url},
        },
    }
