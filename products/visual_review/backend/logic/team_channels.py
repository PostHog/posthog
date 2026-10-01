"""Posting to a team's Slack channel, routed through the repository's ownership registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.core.cache import cache

import structlog
from owners_yaml.resolver import Purpose, team_channel
from owners_yaml.schema import Producer, TeamEntry

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.channels import (
    SlackChannel,
    SlackPostRefused,
    fetch_channel_map,
    find_channel,
    is_shared_channel,
    post_message,
    post_with_join,
)

logger = structlog.get_logger(__name__)

# Visual review posts are automation, so they ask the registry where automation posts rather than
# where the team's people are. That falls back to the people channel when a team never separates the two.
_CHANNEL_PURPOSE: Purpose = "notifications"
# Named so a team can keep visual review out of its channel while other bots keep posting there.
_PRODUCER: Producer = "visual_review"

# Listing channels walks every page of a rate-limited Slack endpoint, and a rate-limited walk returns
# a partial map. Quarantine notices can arrive in bursts, so one listing serves them all for a while.
# The cached shared flag can be stale, so post_to_team checks the channel again before each post.
_CHANNEL_MAP_TTL_SECONDS = 10 * 60


@frozen
class SlackMessage:
    """One post: the blocks Slack renders, and the plain text it shows wherever they do not."""

    blocks: list[dict[str, Any]]
    text: str


@frozen
class Delivery:
    """Where one team's post goes."""

    channel_id: str
    channel_name: str


@frozen
class Workspace:
    """The project's Slack connection, and its channels by name. Read once and shared across teams."""

    integration: Integration
    channels_by_name: Mapping[str, SlackChannel]


def open_workspace(team_id: int) -> Workspace | None:
    """The project's Slack workspace, or None when the project has no Slack integration."""
    integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
    if integration is None:
        logger.info("visual_review.team_post_no_slack_integration", team_id=team_id)
        return None
    cache_key = f"visual_review_slack_channels:{integration.id}"
    channels_by_name = cache.get(cache_key)
    if channels_by_name is None:
        channels_by_name = fetch_channel_map(integration, source="visual_review")
        cache.set(cache_key, channels_by_name, timeout=_CHANNEL_MAP_TTL_SECONDS)
    return Workspace(integration=integration, channels_by_name=channels_by_name)


def resolve_channel(
    team_slug: str, registry: Mapping[str, TeamEntry], channels_by_name: Mapping[str, SlackChannel]
) -> Delivery | None:
    """The team's own notifications channel, or None when it opted out or the name does not resolve."""
    answer = team_channel(team_slug, registry, _CHANNEL_PURPOSE, _PRODUCER)
    if answer.channel is None:
        logger.info("visual_review.team_channel_opted_out", team_slug=team_slug)
        return None
    name = answer.channel.removeprefix("#")
    match = find_channel(channels_by_name, name, allow_shared=False)
    if match.channel is None:
        logger.info("visual_review.team_channel_unusable", team_slug=team_slug, channel_name=name, reason=match.reason)
        return None
    return Delivery(channel_id=match.channel.channel_id, channel_name=name)


def _is_still_internal(slack: SlackIntegration, channel_id: str) -> bool:
    """Whether the channel is still unshared right now. Fails closed when Slack cannot say."""
    try:
        channel = slack.client.conversations_info(channel=channel_id).get("channel")
    except Exception as e:
        logger.warning("visual_review.team_channel_info_failed", channel_id=channel_id, error=str(e))
        return False
    if not channel:
        return False
    return not is_shared_channel(channel)


def post_to_team(
    workspace: Workspace,
    team_slug: str,
    registry: Mapping[str, TeamEntry],
    lead: SlackMessage,
    replies: Sequence[SlackMessage] = (),
) -> bool:
    """Post the lead to the team's channel and the replies in its thread. False when nothing was posted."""
    delivery = resolve_channel(team_slug, registry, workspace.channels_by_name)
    if delivery is None:
        return False

    slack = SlackIntegration(workspace.integration, source="visual_review")
    if not _is_still_internal(slack, delivery.channel_id):
        logger.info("visual_review.team_channel_now_shared", team_slug=team_slug, channel_name=delivery.channel_name)
        return False
    try:
        thread_ts = post_with_join(
            slack, delivery.channel_id, lead.blocks, lead.text, channel_name=delivery.channel_name
        )
    except SlackPostRefused as e:
        logger.warning("visual_review.team_post_refused", team_slug=team_slug, error=str(e))
        return False
    # Without a parent to hang them on, the replies land in the channel as separate top-level posts,
    # which is the noise the thread exists to remove.
    if thread_ts is not None:
        for reply in replies:
            post_message(slack, delivery.channel_id, reply.blocks, reply.text, thread_ts=thread_ts)
    return True
