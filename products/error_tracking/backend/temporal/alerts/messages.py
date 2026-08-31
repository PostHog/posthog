"""Slack message shapes for alert notifications.

Issue names and descriptions come from exception data, so they are attacker
controlled: render them only inside `plain_text` blocks, and escape anything
interpolated into mrkdwn text.
"""

from django.conf import settings

from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

ROOT_HEADLINES = {
    "$error_tracking_issue_created": "🔴 New issue",
    "$error_tracking_issue_reopened": "🔄 Issue reopened",
    "$error_tracking_issue_spiking": "📈 Issue spiking",
    "$error_tracking_issue_assigned": "👤 Issue assigned",
}
DEFAULT_HEADLINE = "🔴 Issue alert"

# Slack rejects header blocks whose complete text exceeds 150 characters, so the
# headline and title are truncated as one composed string.
MAX_HEADER_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 500


def escape_slack_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def issue_url(team_id: int, issue_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/error_tracking/{issue_id}"


def root_headline(event: str) -> str:
    return ROOT_HEADLINES.get(event, DEFAULT_HEADLINE)


def _link_block(inputs: AlertDeliveryWorkflowInputs) -> dict:
    return {
        "type": "actions",
        "block_id": f"error_tracking_issue_actions:{inputs.issue_id}",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "View issue", "emoji": True},
                "url": issue_url(inputs.team_id, inputs.issue_id),
            }
        ],
    }


def _header_text(inputs: AlertDeliveryWorkflowInputs, headline: str) -> str:
    title = inputs.issue_name or "Unknown issue"
    return _truncate(f"{headline}: {title}", MAX_HEADER_LENGTH)


def _build_blocks(inputs: AlertDeliveryWorkflowInputs, *, headline: str) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": _header_text(inputs, headline), "emoji": True}}
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
    blocks.append(_link_block(inputs))
    return blocks


def build_root_message(inputs: AlertDeliveryWorkflowInputs) -> dict:
    headline = root_headline(inputs.event)
    return {
        "blocks": _build_blocks(inputs, headline=headline),
        "text": escape_slack_text(_header_text(inputs, headline)),
        "headline": headline,
    }


def build_root_edit(inputs: AlertDeliveryWorkflowInputs, *, headline: str) -> dict:
    # The headline never changes on edit: it is the thread's identity.
    return {
        "blocks": _build_blocks(inputs, headline=headline),
        "text": escape_slack_text(_header_text(inputs, headline)),
    }


def build_reply_text(inputs: AlertDeliveryWorkflowInputs) -> str | None:
    by = f" by {escape_slack_text(inputs.actor_email)}" if inputs.actor_email else ""
    extra = inputs.extra or {}
    match inputs.event:
        case "$error_tracking_issue_resolved":
            return f"✅ Resolved{by}"
        case "$error_tracking_issue_suppressed":
            return f"🔇 Suppressed{by}"
        case "$error_tracking_issue_assigned":
            return f"👤 Assigned{by}"
        case "$error_tracking_issue_unassigned":
            return f"👤 Unassigned{by}"
        case "$error_tracking_issue_reopened":
            return f"🔄 Reopened{by}"
        case "$error_tracking_issue_created":
            # A created event can reach an existing thread only as a redelivered
            # opener; the root already tells the story.
            return None
        case "$error_tracking_issue_spiking":
            current = extra.get("current_bucket_value")
            baseline = extra.get("computed_baseline")
            if current and baseline:
                return (
                    f"📈 Spiking again: {escape_slack_text(current)} events vs baseline {escape_slack_text(baseline)}"
                )
            return "📈 Spiking again"
        case "$error_tracking_issue_merged":
            merged_count = extra.get("merged_count")
            issues = f"{merged_count} issues" if merged_count and merged_count != "1" else "an issue"
            return f"🔀 Merged {issues} into this issue{by}"
        case "$error_tracking_issue_split":
            split_count = extra.get("split_count")
            issues = f"{split_count} new issues" if split_count and split_count != "1" else "a new issue"
            return f"🔱 Split {issues} out of this issue{by}"
    return None
