from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend import slack_channel_scouts as _slack_channel_scouts
from products.signals.backend.slack_channel_scouts import (
    MAX_SLACK_SCOUT_CHANNELS as MAX_SLACK_SCOUT_CHANNELS,
    SLACK_SCOUT_NAME_MAX_LENGTH as SLACK_SCOUT_NAME_MAX_LENGTH,
    SLACK_SCOUT_SOURCE_PRODUCT as SLACK_SCOUT_SOURCE_PRODUCT,
    SlackChannelSelectionError as SlackChannelSelectionError,
    SlackChannelSource as SlackChannelSource,
    SlackScoutDefinition as SlackScoutDefinition,
)


def list_slack_channel_sources(team: Team, user: User) -> list[SlackChannelSource]:
    """The Slack warehouse sources `user` may view on `team`, each with the channels it syncs."""
    return _slack_channel_scouts.list_slack_channel_sources(team.id, UserAccessControl(user=user, team=team))


def plan_slack_channel_scout(
    *, team: Team, user: User, source_id: str, channel_ids: list[str], steer: str
) -> SlackScoutDefinition:
    """The scout text and pre-check for the picked channels of one of the team's Slack sources `user` may view."""
    return _slack_channel_scouts.plan_slack_channel_scout(
        team_id=team.id,
        user_access_control=UserAccessControl(user=user, team=team),
        source_id=source_id,
        channel_ids=channel_ids,
        steer=steer,
    )
