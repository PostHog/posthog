"""Where visual review posts to a team in Slack, read from the repository's ownership registry."""

from __future__ import annotations

from collections.abc import Mapping

import structlog
from owners_yaml.resolver import Purpose, team_channel
from owners_yaml.schema import Producer, TeamEntry

from posthog.dataclasses import frozen
from posthog.slack.channels import SlackChannel, find_channel

logger = structlog.get_logger(__name__)

# Visual review posts are automation, so they ask the registry where automation posts rather than
# where the team's people are. That falls back to the people channel when a team never separates the two.
_CHANNEL_PURPOSE: Purpose = "notifications"
# Named so a team can keep visual review out of its channel while other bots keep posting there.
_PRODUCER: Producer = "visual_review"


@frozen
class Delivery:
    """Where one team's post goes."""

    channel_id: str
    channel_name: str


def resolve_team_channel(
    team_slug: str,
    registry: Mapping[str, TeamEntry],
    channels_by_name: Mapping[str, SlackChannel],
    *,
    feature: str,
) -> Delivery | None:
    """The team's own notifications channel, or None when it opted out or the name does not resolve."""
    answer = team_channel(team_slug, registry, _CHANNEL_PURPOSE, _PRODUCER)
    if answer.channel is None:
        logger.info("visual_review.team_channel_opted_out", team_slug=team_slug, feature=feature)
        return None
    name = answer.channel.removeprefix("#")
    match = find_channel(channels_by_name, name, allow_shared=False)
    if match.channel is None:
        logger.info(
            "visual_review.team_channel_unusable",
            team_slug=team_slug,
            channel_name=name,
            reason=match.reason,
            feature=feature,
        )
        return None
    return Delivery(channel_id=match.channel.channel_id, channel_name=name)
