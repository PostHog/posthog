"""Slack DMs for @-mentions in task thread messages.

When a thread message @-mentions org members, each mentioned user who opted in
(``CodeUserNotificationSettings.slack_mention_notifications``) gets a DM via the
team's Slack integration. All sends are best-effort: one recipient's failure
never blocks the others, and nothing here can fail message creation (dispatch
happens from a Celery task, after the mention rows commit).
"""

from __future__ import annotations

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.tasks.backend.mentions import render_mention_tokens
from products.tasks.backend.models import CodeUserNotificationSettings, TaskThreadMessage, TaskThreadMessageMention

logger = structlog.get_logger(__name__)

_CONTENT_EXCERPT_MAX_LEN = 300


def _escape_mrkdwn(text: str) -> str:
    """Neutralize Slack control syntax (`&`, `<`, `>`) so message content can't inject mentions/links."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _author_display_name(message: TaskThreadMessage) -> str:
    if message.author_id and message.author:
        name = f"{message.author.first_name or ''} {message.author.last_name or ''}".strip()
        if name:
            return name
        email = (message.author.email or "").strip()
        if email:
            return email.split("@", 1)[0] if "@" in email else email
    return "PostHog agent"


def _content_excerpt(content: str) -> str:
    text = _escape_mrkdwn(render_mention_tokens(content)).strip()
    if len(text) > _CONTENT_EXCERPT_MAX_LEN:
        text = text[:_CONTENT_EXCERPT_MAX_LEN].rstrip() + "…"
    return text


def _build_dm_blocks(message: TaskThreadMessage) -> tuple[str, list[dict]]:
    """The DM payload: plain-text fallback and Block Kit blocks."""
    author = _escape_mrkdwn(_author_display_name(message))
    channel = message.task.channel
    where = f" in *#{_escape_mrkdwn(channel.name)}*" if channel else ""
    body = f"*{author}* mentioned you{where}\n*{_escape_mrkdwn(message.task.title)}*"
    excerpt = _content_excerpt(message.content)
    if excerpt:
        quoted = "\n".join(f"> {line}" for line in excerpt.splitlines())
        body = f"{body}\n{quoted}"

    # The cloud task page (works on mobile) rather than a desktop-only
    # ``posthog-code://`` deep link, matching post_slack_update.py.
    task_url = f"{settings.SITE_URL}/project/{message.team_id}/tasks/{message.task_id}"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open in PostHog"},
                    "url": task_url,
                }
            ],
        },
    ]
    fallback = f"{_author_display_name(message)} mentioned you in a task thread"
    return fallback, blocks


def send_mention_dms_for_message(message_id: str, team_id: int) -> int:
    """DM each opted-in user mentioned in the message. Returns how many DMs were sent.

    Mention rows are unique per (message, user), so a user mentioned twice in
    one message gets one DM. Recipients without a Slack account matching their
    PostHog email are skipped silently.
    """
    message = (
        TaskThreadMessage.objects.for_team(team_id)
        .filter(id=message_id)
        .select_related("author", "task__channel")
        .first()
    )
    if message is None:
        return 0

    mentioned_user_ids = list(
        TaskThreadMessageMention.objects.for_team(team_id)
        .filter(message_id=message.id)
        .values_list("mentioned_user_id", flat=True)
    )
    if not mentioned_user_ids:
        return 0

    recipients = [
        config.user
        for config in CodeUserNotificationSettings.objects.filter(
            user_id__in=mentioned_user_ids, slack_mention_notifications=True
        ).select_related("user")
    ]
    if not recipients:
        return 0

    integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
    if integration is None:
        return 0

    slack = SlackIntegration(integration)
    fallback, blocks = _build_dm_blocks(message)

    sent = 0
    for recipient in recipients:
        try:
            slack_user_id = slack.lookup_user_id_by_email(recipient.email)
            if not slack_user_id:
                continue
            # chat_postMessage to a user id opens the IM if it doesn't already exist.
            slack.client.chat_postMessage(channel=slack_user_id, text=fallback, blocks=blocks)
            sent += 1
        except SlackApiError as exc:
            logger.warning(
                "task_mention_slack_dm_failed",
                message_id=str(message.id),
                user_id=recipient.id,
                error=exc.response.get("error") if exc.response else None,
            )
        except Exception:
            logger.exception("task_mention_slack_dm_failed", message_id=str(message.id), user_id=recipient.id)
    return sent
