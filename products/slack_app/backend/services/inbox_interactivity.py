"""Slack interactivity handlers for the inbox onboarding DM (create/join channel, sources, AI approval).

Kept out of ``api.py`` to keep that module focused on routing — the interactivity dispatcher there
imports ``extract_inbox_hints`` (for region-ownership routing) and the ``handle_inbox_*`` entrypoints.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.http import HttpResponse

import requests
import structlog

from posthog.models.integration import Integration

from products.slack_app.backend import inbox_channel, onboarding

logger = structlog.get_logger(__name__)

SLACK_INTEGRATION_KIND = "slack"


def extract_inbox_hints(payload: dict) -> int | None:
    """Integration id carried by an inbox onboarding interaction, used for region-ownership routing.
    Buttons carry it in their ``value``; the sources/AI checkboxes carry it in their block_id."""
    for action in payload.get("actions", []):
        action_id = action.get("action_id")
        if action_id in (
            onboarding.INBOX_CREATE_ACTION_ID,
            onboarding.INBOX_JOIN_ACTION_ID,
        ):
            try:
                value = json.loads(action.get("value") or "{}")
            except json.JSONDecodeError:
                continue
            integration_id = value.get("integration_id")
            if isinstance(integration_id, int):
                return integration_id
            continue
        block_id = action.get("block_id", "")
        for prefix in (onboarding.INBOX_SOURCES_BLOCK_PREFIX, onboarding.INBOX_AI_APPROVAL_BLOCK_PREFIX):
            if block_id.startswith(f"{prefix}:"):
                suffix = block_id.split(":", 1)[1]
                return int(suffix) if suffix.isdigit() else None
    return None


def post_response_url(response_url: str, body: dict[str, Any]) -> None:
    """POST a body to a Slack interactivity ``response_url``. Best-effort: failures are logged, never
    raised, so a handler that already did its DB work isn't broken by a Slack hiccup."""
    if not response_url:
        return
    try:
        requests.post(response_url, json=body, timeout=3)
    except Exception:
        logger.warning("slack_app_response_url_post_failed", exc_info=True)


def _replace_message_via_response_url(response_url: str, text: str, blocks: list[dict] | None = None) -> None:
    body: dict[str, Any] = {"replace_original": True, "text": text}
    if blocks is not None:
        body["blocks"] = blocks
    post_response_url(response_url, body)


def _post_ephemeral_via_response_url(response_url: str, text: str) -> None:
    """Post a transient note next to the message (doesn't touch the message itself)."""
    post_response_url(response_url, {"response_type": "ephemeral", "replace_original": False, "text": text})


def _inbox_integration_from_payload(payload: dict) -> Integration | None:
    integration_id = extract_inbox_hints(payload)
    slack_team_id = payload.get("team", {}).get("id")
    if not integration_id or not slack_team_id:
        return None
    return Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
        id=integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
        kind=SLACK_INTEGRATION_KIND,
        integration_id=slack_team_id,
    ).first()


def _reconnect_hint() -> str:
    return (
        "PostHog needs the `channels:manage` permission for this. "
        f"Ask a project admin to reconnect Slack ({settings.SITE_URL}/settings/project-integrations), then try again."
    )


def handle_inbox_create(payload: dict) -> HttpResponse:
    """'Create the PostHog inbox channel' button: create #posthog-inbox and invite the clicker."""
    integration = _inbox_integration_from_payload(payload)
    slack_user_id = payload.get("user", {}).get("id", "")
    response_url = payload.get("response_url", "")
    if integration is None or not slack_user_id:
        return HttpResponse(status=200)

    channel = inbox_channel.ensure_inbox_channel(integration)
    if channel is None:
        _replace_message_via_response_url(response_url, f"I couldn't create the channel. {_reconnect_hint()}")
        return HttpResponse(status=200)

    inbox_channel.invite_user_to_inbox(integration, channel[0], slack_user_id)
    dm_channel = payload.get("channel", {}).get("id") or payload.get("container", {}).get("channel_id")
    message_ts = payload.get("message", {}).get("ts")
    if dm_channel and message_ts:
        onboarding.mark_channel_joined(
            integration, slack_user_id, dm_channel, message_ts, payload.get("message", {}).get("blocks", [])
        )
    return HttpResponse(status=200)


def handle_inbox_join(payload: dict) -> HttpResponse:
    """'Join' button: invite the clicker into the team's existing inbox channel."""
    integration = _inbox_integration_from_payload(payload)
    slack_user_id = payload.get("user", {}).get("id", "")
    response_url = payload.get("response_url", "")
    if integration is None or not slack_user_id:
        return HttpResponse(status=200)

    channel = inbox_channel.ensure_inbox_channel(integration)
    if channel is None:
        _replace_message_via_response_url(
            response_url, "Your team's inbox channel isn't available right now — please try again shortly."
        )
        return HttpResponse(status=200)

    if inbox_channel.invite_user_to_inbox(integration, channel[0], slack_user_id):
        dm_channel = payload.get("channel", {}).get("id") or payload.get("container", {}).get("channel_id")
        message_ts = payload.get("message", {}).get("ts")
        if dm_channel and message_ts:
            onboarding.mark_channel_joined(
                integration, slack_user_id, dm_channel, message_ts, payload.get("message", {}).get("blocks", [])
            )
    else:
        _replace_message_via_response_url(response_url, f"I couldn't add you. {_reconnect_hint()}")
    return HttpResponse(status=200)


def handle_inbox_ai_approval(payload: dict) -> HttpResponse:
    """'Approve AI data processing' checkbox: ticking it approves. The approve helper re-checks ADMIN+ server-side."""
    integration = _inbox_integration_from_payload(payload)
    slack_user_id = payload.get("user", {}).get("id", "")
    action = next(
        (a for a in payload.get("actions", []) if a.get("action_id") == onboarding.INBOX_AI_APPROVAL_ACTION_ID),
        None,
    )
    ticked = any(o.get("value") == "approve" for o in (action or {}).get("selected_options", []))
    if integration and slack_user_id and ticked:
        if not onboarding.approve_ai_data_processing(integration, slack_user_id):
            _post_ephemeral_via_response_url(
                payload.get("response_url", ""),
                ":warning: Only an organization admin can approve AI data processing.",
            )
    return HttpResponse(status=200)


def handle_inbox_sources(payload: dict) -> HttpResponse:
    """Sources checkbox toggled: sync the team's sources to the new selection, in place."""
    integration = _inbox_integration_from_payload(payload)
    slack_user_id = payload.get("user", {}).get("id", "")
    if integration is None or not slack_user_id:
        return HttpResponse(status=200)
    action = next(
        (a for a in payload.get("actions", []) if a.get("action_id") == onboarding.INBOX_SOURCES_CHECKBOXES_ACTION),
        None,
    )
    selected = [o.get("value") for o in (action or {}).get("selected_options", []) if o.get("value")]
    blocked = onboarding.apply_sources_selection(integration, slack_user_id, selected)
    if blocked:
        _post_ephemeral_via_response_url(
            payload.get("response_url", ""),
            f":warning: Approve AI data processing first to turn on *{', '.join(blocked)}*.",
        )
    return HttpResponse(status=200)
