from datetime import datetime

from posthog.dataclasses import frozen

from products.slack_app.backend.facade.enums import SlackReactionKind, SlackSetupStepKey

# Slack rate limits conversations.join, and a long list in one request would hold the request open.
MAX_CHANNELS_TO_JOIN = 20


class SlackSetupNotFound(Exception):
    """The project has no Slack app install with this id."""


class WorkspaceSettingsError(Exception):
    """The person cannot change this workspace setting. The message says why."""


class SlackSettingsInvalid(Exception):
    """A setting value that PostHog or Slack would refuse. The message says why."""


class ChannelCatalogBusy(Exception):
    """The workspace cannot list its Slack channels now. The message tells the person what to do."""


@frozen
class ProjectOption:
    integration_id: int
    project_name: str
    organization_name: str


@frozen
class WorkspaceSetup:
    integration_id: int
    slack_workspace_name: str | None
    open_slack_url: str | None
    steps: tuple[SlackSetupStepKey, ...]
    project_options: tuple[ProjectOption, ...]
    can_post_channel_welcome: bool


@frozen
class SlackReactionChoice:
    """One stored reaction. A None field inherits from the next level."""

    emoji: str | None = None
    enabled: bool | None = None


@frozen
class SlackResolvedReaction:
    emoji: str
    enabled: bool


@frozen
class SlackWorkspaceSettings:
    reactions: dict[SlackReactionKind, SlackReactionChoice]
    external_channels_enabled: bool


@frozen
class SlackPersonalSettings:
    # None when the person has not linked a Slack account in this workspace.
    slack_user_id: str | None
    reactions: dict[SlackReactionKind, SlackReactionChoice]
    effective_reactions: dict[SlackReactionKind, SlackResolvedReaction]


@frozen
class SlackAppSettings:
    integration_id: int
    slack_workspace_name: str | None
    can_edit_workspace: bool
    workspace: SlackWorkspaceSettings
    personal: SlackPersonalSettings


@frozen
class SlackChannelSettings:
    slack_channel_id: str
    default_integration_id: int | None
    default_repository: str | None
    untagged_question_mode: str | None
    updated_by_name: str | None
    updated_at: datetime | None


@frozen
class ChannelOption:
    id: str
    name: str
    is_member: bool


@frozen
class ChannelJoinResult:
    channel_id: str
    error: str | None
