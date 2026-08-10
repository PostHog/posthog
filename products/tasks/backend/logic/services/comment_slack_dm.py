"""Slack DM delivery for PostHog Code comment notifications.

A second channel for the three recipient kinds the in-app Activity feed already gets: a mention,
a reply to your comment, a comment on something you own. Recipients and the personal-channel
exclusion are decided by ``comment_activity``; this module only decides whether each recipient
wants a DM, may still see the comment, and where to send it.

Delivery is best-effort. The Activity row is the durable notification, so a Slack failure is
logged and dropped rather than retried — which also means a retry can't double-DM someone without
a per-recipient sent marker to store.
"""

from collections.abc import Mapping
from uuid import UUID

from django.conf import settings

import structlog

from posthog.comment.formatting import escape_slack_mrkdwn, rich_content_to_slack_payload
from posthog.models.comment import Comment
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.tasks.backend.logic.services.comment_activity import target_is_accessible
from products.tasks.backend.models import Task, TaskCommentActivity

logger = structlog.get_logger(__name__)

# Opt-in: having linked a Slack account is not consent to have your comments forwarded into it.
SLACK_DM_SETTING = "code_comments_slack_dm"

# Slack allows 3000 characters per section; a DM that long is unreadable, and the link to the full
# thread is right there in the heading.
_BODY_LIMIT = 800

_HEADINGS: Mapping[str, str] = {
    TaskCommentActivity.Kind.MENTION: "{author} mentioned you on {link}",
    TaskCommentActivity.Kind.THREAD_REPLY: "{author} replied to your comment on {link}",
    TaskCommentActivity.Kind.OWNED_ITEM_COMMENT: "{author} commented on {link}",
}


def send_comment_slack_dms(*, team_id: int, comment_id: UUID, task_id: UUID, recipients: Mapping[int, str]) -> None:
    """DM each recipient who opted in, can still see the comment, and has linked Slack.

    ``recipients`` is the map ``comment_activity`` just projected: user id to activity kind.
    """
    if not recipients:
        return

    comment = Comment.objects.filter(team_id=team_id, id=comment_id).select_related("created_by").first()
    if comment is None:
        return
    skip_reason = _skip_reason(comment)
    if skip_reason:
        logger.info("comment_slack_dm_skipped", comment_id=str(comment_id), reason=skip_reason)
        return

    # Cheapest gate first: most comments have no opted-in recipient, and this keeps the flag call
    # (a network hop) off that path.
    wanted = _recipients_wanting_dms(team_id=team_id, comment=comment, recipients=recipients)
    if not wanted:
        return

    integration = Integration.objects.filter(team_id=team_id, kind=Integration.IntegrationKind.SLACK).first()
    if integration is None or not integration.integration_id:
        return
    # The flag that gates the Slack identity link itself. Gating delivery on it too means an org
    # that never had the link flow can't receive DMs, and turning it off halts delivery without a
    # deploy. Skipped in local dev, where flags evaluate against the developer's own instance and
    # the gate would otherwise fail closed on every machine — the same default-on-in-dev treatment
    # the desktop flags get.
    if not settings.DEBUG and not is_slack_app_oauth_enabled(integration, integration.integration_id):
        return

    task = Task.objects.filter(team_id=team_id, id=task_id).only("id", "team_id", "title").first()
    if task is None:
        return

    organization_id = Team.objects.filter(id=team_id).values_list("organization_id", flat=True).first()
    client = SlackIntegration(integration).client
    for user_id, kind in wanted.items():
        # Re-checked at send time rather than trusting the projected recipient set: the in-app feed
        # re-checks visibility on every read, and a DM can't be taken back.
        if not target_is_accessible(
            team_id=team_id, user_id=user_id, task_id=task_id, scope=comment.scope, item_id=comment.item_id
        ):
            continue
        slack_user_id = _slack_user_id(user_id, integration.integration_id)
        if not slack_user_id:
            continue
        fallback, blocks = _message(kind=kind, comment=comment, task=task, organization_id=organization_id)
        try:
            client.chat_postMessage(channel=slack_user_id, text=fallback, blocks=blocks, unfurl_links=False)
        except Exception as exc:
            logger.warning("comment_slack_dm_failed", comment_id=str(comment_id), user_id=user_id, error=str(exc))


def _skip_reason(comment: Comment) -> str | None:
    """Replies that aren't messages. Reactions and resolve/reopen are both stored as reply
    comments, so without this a thumbs-up would DM everyone in the thread."""
    context = comment.item_context if isinstance(comment.item_context, dict) else {}
    if context.get("is_emoji"):
        return "emoji"
    if context.get("threadState"):
        return "thread_state"
    if context.get("from_slack"):
        return "from_slack"
    return None


def _recipients_wanting_dms(*, team_id: int, comment: Comment, recipients: Mapping[int, str]) -> dict[int, str]:
    """Narrow the Activity recipients to the ones who asked to be DMed.

    ``THREAD_REPLY`` narrows further: the Activity feed notifies every thread participant, but the
    DM says "replied to your comment", so only the thread's author gets one.
    """
    # Read the raw partial settings rather than the merged `notification_settings` property: the
    # setting is opt-in, so an absent key means off and there's no default to merge in.
    opted_in = {
        user_id
        for user_id, partial in User.objects.filter(id__in=list(recipients)).values_list(
            "id", "partial_notification_settings"
        )
        if isinstance(partial, dict) and partial.get(SLACK_DM_SETTING) is True
    }
    if not opted_in:
        return {}

    root_author_id: int | None = None
    if any(kind == TaskCommentActivity.Kind.THREAD_REPLY for uid, kind in recipients.items() if uid in opted_in):
        root_author_id = (
            Comment.objects.filter(team_id=team_id, id=comment.source_comment_id or comment.id)
            .values_list("created_by_id", flat=True)
            .first()
        )

    wanted: dict[int, str] = {}
    for user_id, kind in recipients.items():
        if user_id not in opted_in:
            continue
        if kind == TaskCommentActivity.Kind.THREAD_REPLY and user_id != root_author_id:
            continue
        wanted[user_id] = kind
    return wanted


def _slack_user_id(user_id: int, slack_team_id: str) -> str | None:
    link = (
        UserIntegration.objects.filter(
            user_id=user_id,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=slack_team_id,
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link else None


def _author_name(comment: Comment) -> str:
    author = comment.created_by
    if author is None:
        return "Someone"
    return f"{author.first_name} {author.last_name}".strip() or author.email or "Someone"


def _message(*, kind: str, comment: Comment, task: Task, organization_id: str | UUID | None) -> tuple[str, list[dict]]:
    url = f"{settings.SITE_URL}/project/{task.team_id}/tasks/{task.id}"
    title = task.title or "a task"
    author = _author_name(comment)
    template = _HEADINGS.get(kind, _HEADINGS[TaskCommentActivity.Kind.MENTION])
    # A pipe in the title would end the link label early, so it can't survive into the label.
    label = escape_slack_mrkdwn(title).replace("|", "-")
    heading = template.format(author=f"*{escape_slack_mrkdwn(author)}*", link=f"<{url}|{label}>")
    # Plain-text twin for the notification preview and older clients.
    fallback = template.format(author=author, link=title)

    body, _ = rich_content_to_slack_payload(
        comment.rich_content, comment.content or "", include_images=False, organization_id=organization_id
    )
    body = body.strip()
    if len(body) > _BODY_LIMIT:
        body = body[: _BODY_LIMIT - 1] + "…"
    text = f"{heading}\n\n> " + body.replace("\n", "\n> ") if body else heading
    return fallback, [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
