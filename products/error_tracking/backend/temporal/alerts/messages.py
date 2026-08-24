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
}

MAX_TITLE_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 500


def escape_slack_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def issue_url(team_id: int, issue_id: str) -> str:
    return f"{settings.SITE_URL}/project/{team_id}/error_tracking/{issue_id}"


def build_root_message(inputs: AlertDeliveryWorkflowInputs) -> dict:
    headline = ROOT_HEADLINES.get(inputs.event, "🔴 Issue alert")
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
    context_parts = []
    if inputs.status:
        context_parts.append(f"Status: {escape_slack_text(inputs.status)}")
    context_parts.append(f"<{issue_url(inputs.team_id, inputs.issue_id)}|View issue>")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context_parts)}]})
    return {
        "blocks": blocks,
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
