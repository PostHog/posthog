"""Resolving what kind of Slack conversation a thread lives in.

The answer decides whether the thread's task is readable by the whole team or stays with
its creator, so it is resolved once at task creation and stored on the thread mapping
rather than recomputed per request.

The three steps below are ordered cheapest-first, but the ordering is load-bearing rather
than an optimization: ``conversations.info`` is the only step that costs a round-trip, and
it is the one step that cannot answer for a DM. ``im:read`` is not in the scopes we request
and ``mpim:read`` is still in Slack review, so the call fails outright on a ``D…`` id.
Steps 1 and 2 settle direct messages without it, leaving the API responsible only for the
public-vs-private split among channels, where ``channels:read`` and ``groups:read`` do apply.
"""

from typing import Any

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.models import SlackThreadTaskMapping

logger = structlog.get_logger(__name__)

ConversationType = SlackThreadTaskMapping.ConversationType

# `channel_type` rides on `message` events and is what the event router already keys on to
# send DMs to the assistant surface. `group` is Slack's wire name for a private channel.
_CHANNEL_TYPE_TO_CONVERSATION_TYPE = {
    "im": ConversationType.IM,
    "mpim": ConversationType.MPIM,
    "group": ConversationType.PRIVATE_CHANNEL,
    "channel": ConversationType.PUBLIC_CHANNEL,
}


def resolve_conversation_type(
    slack: SlackIntegration,
    event: dict[str, Any],
    channel_id: str,
) -> SlackThreadTaskMapping.ConversationType:
    """The shape of the conversation ``channel_id`` names.

    Never raises: an unresolvable conversation comes back as ``UNKNOWN``, which reads as
    non-private downstream. Task creation must not fail over this.
    """
    channel_type = event.get("channel_type")
    if channel_type in _CHANNEL_TYPE_TO_CONVERSATION_TYPE:
        return _CHANNEL_TYPE_TO_CONVERSATION_TYPE[channel_type]

    # `app_mention` carries no `channel_type` and is the primary way a new task starts, so
    # the id prefix is the only signal left for a DM. Slack discourages relying on prefixes,
    # which is why it is a fallback and not the first check — but `D…` is unambiguous, and
    # the alternative (`conversations.info`) is exactly the call we lack the scope to make.
    # `G…` is deliberately not mapped: it means either a group DM or a legacy private
    # channel. Both are shared conversations, so the distinction does not change who may
    # read the task — only which label we store — and the lookup below can try to get it right.
    if channel_id.startswith("D"):
        return ConversationType.IM

    return _channel_privacy_from_slack(slack, channel_id)


def _channel_privacy_from_slack(
    slack: SlackIntegration,
    channel_id: str,
) -> SlackThreadTaskMapping.ConversationType:
    """Split public from private for something we already believe is a channel."""
    try:
        channel = slack.client.conversations_info(channel=channel_id).get("channel") or {}
    except SlackApiError as e:
        # Most likely an install predating `channels:read`/`groups:read`, or a ratelimit.
        logger.warning(
            "slack_app_conversation_type_lookup_failed",
            channel_id=channel_id,
            error=e.response.get("error"),
        )
        return ConversationType.UNKNOWN
    except Exception:
        logger.warning("slack_app_conversation_type_lookup_failed", channel_id=channel_id, exc_info=True)
        return ConversationType.UNKNOWN

    # A group DM reached here only if its id did not start with `D`; `conversations.info`
    # still labels it, so honour that before falling back to the private/public split.
    if channel.get("is_im"):
        return ConversationType.IM
    if channel.get("is_mpim"):
        return ConversationType.MPIM
    if "is_private" not in channel:
        return ConversationType.UNKNOWN
    return ConversationType.PRIVATE_CHANNEL if channel["is_private"] else ConversationType.PUBLIC_CHANNEL
