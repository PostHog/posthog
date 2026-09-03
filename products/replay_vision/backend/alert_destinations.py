"""Build HogFunction configurations for replay vision alert notifications."""

from __future__ import annotations

from typing import Literal

from products.alerts.backend.destination_configs import DestinationType, EventKindSpec

EventKind = Literal["firing", "resolved", "broken", "errored", "match"]
VISION_DESTINATION_TYPES = (DestinationType.SLACK, DestinationType.WEBHOOK)

_PRODUCT_LABEL = "replay vision alert"

_ALERT_URL = "{project.url}/replay-vision/{event.properties.scanner_id}?tab=alerts"
_OBSERVATIONS_URL = "{project.url}/replay-vision/{event.properties.scanner_id}?tab=observations"

_FIRE_RESOLVE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "scanner_id": "{event.properties.scanner_id}",
    "scanner_name": "{event.properties.scanner_name}",
    "metric": "{event.properties.metric}",
    "metric_value": "{event.properties.metric_value}",
    "threshold": "{event.properties.threshold}",
    "direction": "{event.properties.direction}",
    "window_days": "{event.properties.window_days}",
    "observations_url": _OBSERVATIONS_URL,
    "alert_url": _ALERT_URL,
}

_BROKEN_ERRORED_BASE_DATA: dict[str, str] = {
    "alert_id": "{event.properties.alert_id}",
    "alert_name": "{event.properties.alert_name}",
    "scanner_id": "{event.properties.scanner_id}",
    "scanner_name": "{event.properties.scanner_name}",
    "consecutive_failures": "{event.properties.consecutive_failures}",
    "alert_url": _ALERT_URL,
}


EVENT_KIND_CONFIG: dict[EventKind, EventKindSpec] = {
    "firing": EventKindSpec(
        event_id="$replay_vision_alert_firing",
        display_kind="firing",
        header="🔴 Replay vision alert '{event.properties.alert_name}' is firing",
        details=(
            (
                "Threshold breached",
                "{event.properties.metric_label} is {event.properties.metric_value} over the last "
                "{event.properties.window_label} (threshold: {event.properties.direction} {event.properties.threshold})",
            ),
        ),
        primary_action_url=_OBSERVATIONS_URL,
        primary_action_label="View observations",
        webhook_body={
            "id": "{event.uuid}",
            "type": "replay_vision_alert.firing",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "resolved": EventKindSpec(
        event_id="$replay_vision_alert_resolved",
        display_kind="resolved",
        header="🟢 Replay vision alert '{event.properties.alert_name}' has resolved",
        details=(
            (
                "Current value",
                "{event.properties.metric_label} is {event.properties.metric_value} over the last "
                "{event.properties.window_label} (threshold: {event.properties.direction} {event.properties.threshold})",
            ),
        ),
        primary_action_url=_OBSERVATIONS_URL,
        primary_action_label="View observations",
        webhook_body={
            "id": "{event.uuid}",
            "type": "replay_vision_alert.resolved",
            "timestamp": "{event.properties.triggered_at}",
            "data": _FIRE_RESOLVE_DATA,
        },
        product_label=_PRODUCT_LABEL,
    ),
    "broken": EventKindSpec(
        event_id="$replay_vision_alert_auto_disabled",
        display_kind="auto-disabled",
        header="⚠️ Replay vision alert '{event.properties.alert_name}' was auto-disabled",
        details=(
            ("Reason", "{event.properties.consecutive_failures} consecutive check failures."),
            ("Last error", "{event.properties.last_error_message}"),
        ),
        primary_action_url=_ALERT_URL,
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "replay_vision_alert.auto_disabled",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "last_error_message": "{event.properties.last_error_message}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
    "errored": EventKindSpec(
        event_id="$replay_vision_alert_errored",
        display_kind="errored",
        header="🟡 Replay vision alert '{event.properties.alert_name}' couldn't evaluate",
        details=(
            ("Reason", "{event.properties.error_message}"),
            ("Failure count", "{event.properties.consecutive_failures}"),
        ),
        primary_action_url=_ALERT_URL,
        primary_action_label="View alert",
        webhook_body={
            "id": "{event.uuid}",
            "type": "replay_vision_alert.errored",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                **_BROKEN_ERRORED_BASE_DATA,
                "error_message": "{event.properties.error_message}",
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
    "match": EventKindSpec(
        event_id="$replay_vision_alert_match",
        display_kind="match",
        header="🔔 {event.properties.matched_count} new matching observations for '{event.properties.alert_name}'",
        details=(("Matches", "{event.properties.summary}"),),
        primary_action_url=_OBSERVATIONS_URL,
        primary_action_label="View observations",
        webhook_body={
            "id": "{event.uuid}",
            "type": "replay_vision_alert.match",
            "timestamp": "{event.properties.triggered_at}",
            "data": {
                "alert_id": "{event.properties.alert_id}",
                "alert_name": "{event.properties.alert_name}",
                "scanner_id": "{event.properties.scanner_id}",
                "scanner_name": "{event.properties.scanner_name}",
                "matched_count": "{event.properties.matched_count}",
                "observation_ids": "{event.properties.observation_ids}",
                "observations_url": _OBSERVATIONS_URL,
                "alert_url": _ALERT_URL,
            },
        },
        product_label=_PRODUCT_LABEL,
    ),
}

# Lifecycle kinds provisioned as destinations for metric alerts; match alerts get only "match".
METRIC_EVENT_KINDS: tuple[EventKind, ...] = ("firing", "resolved", "broken", "errored")
MATCH_EVENT_KINDS: tuple[EventKind, ...] = ("match",)

VISION_ALERT_EVENT_IDS = tuple(spec.event_id for spec in EVENT_KIND_CONFIG.values())

VISION_ALERT_SLACK_CONTEXT_ELEMENTS = (
    "Scanner: {event.properties.scanner_name_mrkdwn}",
    "Project: <{project.url}|{project.name}>",
)


def escape_slack_mrkdwn(text: str) -> str:
    """User-editable values interpolated into Slack mrkdwn must not carry control
    syntax like <!channel> or <url|label>; webhooks keep the raw value."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
