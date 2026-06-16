"""Build HogFunction configurations for logs alert notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from products.logs.backend.models import LogsAlertConfiguration

EventKind = Literal["firing", "resolved", "broken", "errored"]


@dataclass(frozen=True)
class EventKindSpec:
    event_id: str
    display_kind: str
    header: str
    # Plain-text (label, value) pairs; each destination renders these in its own markup.
    details: tuple[tuple[str, str], ...]
    button_url: str
    button_label: str
    webhook_body: dict[str, Any]

    def destination_description(self, alert_name: str) -> str:
        return f'Sends {self.display_kind} notifications for logs alert "{alert_name}".'


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
        button_url="{project.url}/logs?{event.properties.logs_url_params}",
        button_label="View logs",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
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
        button_url="{project.url}/logs?{event.properties.logs_url_params}",
        button_label="View logs",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.resolved",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
    ),
    "broken": EventKindSpec(
        event_id="$logs_alert_auto_disabled",
        display_kind="auto-disabled",
        header="⚠️ Log alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.last_error_message}"),
        ),
        button_url="{project.url}/logs/alerts/{event.properties.alert_id}",
        button_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.auto_disabled",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "last_error_message": "{event.properties.last_error_message}",
            },
        },
    ),
    "errored": EventKindSpec(
        event_id="$logs_alert_errored",
        display_kind="errored",
        header="🟡 Log alert '{event.properties.alert_name}' couldn't evaluate",
        details=(
            ("Reason", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        button_url="{project.url}/logs/alerts/{event.properties.alert_id}",
        button_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "logs_alert.errored",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "error_message": "{event.properties.error_message}",
            },
        },
    ),
}

EVENT_KINDS: tuple[EventKind, ...] = tuple(EVENT_KIND_CONFIG.keys())

# HogFunction.name is `models.CharField(max_length=400)` — clip rendered names to fit.
_HOG_FUNCTION_NAME_MAX_LEN = 400


def _clip_name(name: str) -> str:
    if len(name) <= _HOG_FUNCTION_NAME_MAX_LEN:
        return name
    return name[: _HOG_FUNCTION_NAME_MAX_LEN - 1] + "…"


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


def _slack_body(spec: EventKindSpec) -> str:
    # Slack mrkdwn: *single asterisks* for bold, one line per detail.
    return "\n".join(f"*{label}:* {value}" for label, value in spec.details)


def _slack_blocks(spec: EventKindSpec) -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": spec.header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _slack_body(spec)}},
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


def _teams_text(spec: EventKindSpec) -> str:
    # The Microsoft Teams template renders a single Adaptive Card TextBlock from `text`, so fold
    # the header, details, and action into one markdown string (the button becomes an inline link).
    # Adaptive Card markdown: **double asterisks** for bold, blank lines between paragraphs.
    details = "\n\n".join(f"**{label}:** {value}" for label, value in spec.details)
    return f"**{spec.header}**\n\n{details}\n\n[{spec.button_label}]({spec.button_url})"


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
        "name": _clip_name(f"Logs alert — {alert.name} ({spec.display_kind}) → Slack #{channel_display}"),
        "description": spec.destination_description(alert.name),
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
        "name": _clip_name(f"Logs alert — {alert.name} ({spec.display_kind}) → Webhook {webhook_url}"),
        "description": spec.destination_description(alert.name),
        "template_id": "template-webhook",
        "inputs": {
            "body": {"value": spec.webhook_body},
            "url": {"value": webhook_url},
            "headers": {"value": {"Content-Type": "application/json", "X-PostHog-Webhook-Version": "1"}},
        },
    }


def build_teams_config(
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
        "name": _clip_name(f"Logs alert — {alert.name} ({spec.display_kind}) → Microsoft Teams"),
        "description": spec.destination_description(alert.name),
        "template_id": "template-microsoft-teams",
        "inputs": {
            "webhookUrl": {"value": webhook_url},
            "text": {"value": _teams_text(spec)},
        },
    }
