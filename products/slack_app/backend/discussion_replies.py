"""Ingest Slack thread replies on mirrored discussion threads back into PostHog as comments.

The outbound half (PostHog discussion -> Slack thread) lives in posthog/helpers/slack_thread_mirror.py
and the send_to_slack action. This is the inbound half: when someone replies in a Slack thread that a
discussion is mirrored to, save their message as a reply Comment on that discussion.
"""

from typing import Any

import structlog

from posthog.comment.formatting import slack_to_content_and_rich_content
from posthog.helpers.slack_identity import resolve_posthog_user_for_slack, resolve_slack_user
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)


def try_ingest_discussion_reply(
    event: dict[str, Any],
    candidates: list[Integration],
    channel: str | None,
    thread_ts: str | None,
    slack_team_id: str,
) -> bool:
    """Save a Slack thread reply as a discussion comment if the thread is mirrored.

    Returns True when the reply belonged to a mirrored discussion (so the caller stops treating
    it as coding-agent work), False when the thread isn't a mirrored discussion.

    Echo prevention is twofold: the caller's ``_thread_message_ignore_reason`` already drops the
    bot's own posts before we get here, and the comment we create is flagged ``from_slack`` so the
    outbound mirror signal won't bounce it straight back to Slack.
    """
    if not channel or not thread_ts:
        return False

    # candidates are this workspace's integrations in this region; bound the cross-team lookup to them.
    candidate_ids = [c.id for c in candidates]
    mirror = (
        CommentSlackThread.objects.unscoped()
        .filter(integration_id__in=candidate_ids, slack_channel_id=channel, slack_thread_ts=thread_ts)
        .select_related("integration__team")
        .first()
    )
    if mirror is None:
        return False

    integration = mirror.integration
    team = integration.team
    slack_user_id = str(event.get("user") or "")
    user_info = resolve_slack_user(SlackIntegration(integration).client, slack_user_id)
    posthog_user = resolve_posthog_user_for_slack(user_info.get("email"), team)

    content, rich_content = slack_to_content_and_rich_content(event.get("text", ""), event.get("blocks"))
    if not content and not rich_content:
        return True

    Comment.objects.create(
        team=team,
        scope=mirror.scope,
        item_id=mirror.item_id,
        # The reply hangs off the mirrored thread's root comment (None only for whole-item mirrors).
        source_comment_id=mirror.source_comment_id,
        content=content,
        rich_content=rich_content,
        # Slack users without a matching PostHog account stay author-less; their identity rides in item_context.
        created_by=posthog_user,
        item_context={
            "from_slack": True,
            "slack_user_id": slack_user_id,
            "slack_author_name": user_info["name"],
            "slack_author_email": user_info.get("email"),
            "slack_author_avatar": user_info.get("avatar"),
        },
    )
    logger.info(
        "slack_discussion_reply_ingested",
        team_id=team.id,
        scope=mirror.scope,
        item_id=mirror.item_id,
        slack_team_id=slack_team_id,
    )
    return True
