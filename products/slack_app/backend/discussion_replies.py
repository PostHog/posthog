"""Ingest Slack thread replies on mirrored discussion threads back into PostHog as comments.

The outbound half (PostHog discussion -> Slack thread) lives in posthog/helpers/slack_thread_mirror.py
and the send_to_slack action. This is the inbound half: when someone replies in a Slack thread that a
discussion is mirrored to, save their message as a reply Comment on that discussion. Only the routing
decision happens here, on the webhook request thread — the Slack profile lookup and comment write run
in a Celery task so the events endpoint can ack within Slack's deadline and failures get retries.
"""

from typing import Any

import structlog

from posthog.models.comment import CommentSlackThread
from posthog.models.integration import Integration
from posthog.tasks.comment_slack_sync import ingest_slack_discussion_reply

from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)


def try_ingest_discussion_reply(
    event: dict[str, Any],
    candidates: list[Integration],
    channel: str | None,
    thread_ts: str | None,
    slack_team_id: str,
) -> bool:
    """Enqueue a Slack thread reply for ingestion as a discussion comment if the thread is mirrored.

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
        .only("id")
        .first()
    )
    if mirror is None:
        return False

    # A thread can be both a mirrored discussion and an agent-task thread (someone @-mentioned the
    # agent in it). The agent followup pipeline takes precedence — claiming the reply here would
    # silently swallow instructions meant for the agent.
    if SlackThreadTaskMapping.objects.filter(
        integration_id__in=candidate_ids, channel=channel, thread_ts=thread_ts
    ).exists():
        return False

    # ts is the ingestion idempotency key — without it, Slack's event redelivery would create
    # duplicate comments. A real message always carries one; claim the event but don't ingest.
    if not event.get("ts"):
        logger.warning("slack_discussion_reply_missing_ts", comment_slack_thread_id=str(mirror.id))
        return True

    ingest_slack_discussion_reply.delay(
        comment_slack_thread_id=str(mirror.id),
        slack_user_id=str(event.get("user") or ""),
        text=str(event.get("text") or ""),
        blocks=event.get("blocks") if isinstance(event.get("blocks"), list) else None,
        message_ts=str(event.get("ts") or ""),
    )
    logger.info(
        "slack_discussion_reply_enqueued",
        comment_slack_thread_id=str(mirror.id),
        slack_team_id=slack_team_id,
    )
    return True
