"""Slack message shapes for alert notifications.

Issue names and descriptions come from exception data, so they are attacker
controlled: render them only inside `plain_text` blocks, and escape anything
interpolated into mrkdwn text.
"""

import json

from django.conf import settings

from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

ROOT_HEADLINES = {
    "$error_tracking_issue_created": "🔴 New issue",
    "$error_tracking_issue_reopened": "🔄 Issue reopened",
    "$error_tracking_issue_spiking": "📈 Issue spiking",
}
DEFAULT_HEADLINE = "🔴 Issue alert"

# Callbacks land on products/slack_app's interactivity endpoint once handlers
# exist for these ids; until then the buttons render but clicks are no-ops.
RESOLVE_ACTION_ID = "error_tracking_issue_resolve"
ASSIGN_ME_ACTION_ID = "error_tracking_issue_assign_me"
SUPPRESS_ACTION_ID = "error_tracking_issue_suppress"

MAX_TITLE_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 500


def escape_slack_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def issue_url(team_id: int, issue_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/error_tracking/{issue_id}"


def root_headline(event: str) -> str:
    return ROOT_HEADLINES.get(event, DEFAULT_HEADLINE)


def _button(text: str, **kwargs: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": text, "emoji": True}, **kwargs}


def _actions_block(inputs: AlertDeliveryWorkflowInputs, *, include_actions: bool) -> dict:
    # The value payload carries what a future handler needs before any lookup:
    # the region-routing team id and the issue to act on.
    value = json.dumps({"team_id": inputs.team_id, "issue_id": inputs.issue_id}, separators=(",", ":"))
    elements: list[dict] = []
    if include_actions:
        elements.extend(
            [
                _button("Resolve", action_id=RESOLVE_ACTION_ID, value=value, style="primary"),
                _button("Assign to me", action_id=ASSIGN_ME_ACTION_ID, value=value),
                _button("Suppress", action_id=SUPPRESS_ACTION_ID, value=value),
            ]
        )
    elements.append(_button("View issue", url=issue_url(inputs.team_id, inputs.issue_id)))
    return {
        "type": "actions",
        "block_id": f"error_tracking_issue_actions:{inputs.issue_id}",
        "elements": elements,
    }


def _build_blocks(inputs: AlertDeliveryWorkflowInputs, *, headline: str, include_actions: bool) -> list[dict]:
    title = _truncate(inputs.issue_name or "Unknown issue", MAX_TITLE_LENGTH)
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{headline}: {title}", "emoji": True}}
    ]
    if inputs.issue_description:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": _truncate(inputs.issue_description, MAX_DESCRIPTION_LENGTH),
                },
            }
        )
    if inputs.status:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Status: {escape_slack_text(inputs.status)}"}],
            }
        )
    blocks.append(_actions_block(inputs, include_actions=include_actions))
    return blocks


def build_root_message(inputs: AlertDeliveryWorkflowInputs) -> dict:
    headline = root_headline(inputs.event)
    title = _truncate(inputs.issue_name or "Unknown issue", MAX_TITLE_LENGTH)
    return {
        "blocks": _build_blocks(inputs, headline=headline, include_actions=True),
        "text": f"{headline}: {escape_slack_text(title)}",
        "headline": headline,
    }


def build_root_edit(inputs: AlertDeliveryWorkflowInputs, *, headline: str, include_actions: bool) -> dict:
    title = _truncate(inputs.issue_name or "Unknown issue", MAX_TITLE_LENGTH)
    return {
        "blocks": _build_blocks(inputs, headline=headline, include_actions=include_actions),
        "text": f"{headline}: {escape_slack_text(title)}",
    }


def build_reply_text(inputs: AlertDeliveryWorkflowInputs) -> str | None:
    by = f" by {escape_slack_text(inputs.actor_email)}" if inputs.actor_email else ""
    match inputs.event:
        case "$error_tracking_issue_resolved":
            return f"✅ Resolved{by}"
        case "$error_tracking_issue_suppressed":
            return f"🔇 Suppressed{by}"
        case "$error_tracking_issue_assigned":
            return f"👤 Assigned{by}"
        case "$error_tracking_issue_reopened":
            return f"🔄 Reopened{by}"
        case "$error_tracking_issue_spiking":
            extra = inputs.extra or {}
            current = extra.get("current_bucket_value")
            baseline = extra.get("computed_baseline")
            if current and baseline:
                return (
                    f"📈 Spiking again: {escape_slack_text(current)} events vs baseline {escape_slack_text(baseline)}"
                )
            return "📈 Spiking again"
    return None
