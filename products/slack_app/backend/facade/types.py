from posthog.dataclasses import frozen

from products.slack_app.backend.facade.enums import SlackSetupStepKey

# Slack rate limits conversations.join, and a long list in one request would hold the request open.
MAX_CHANNELS_TO_JOIN = 20


class SlackSetupNotFound(Exception):
    """The project has no Slack app install with this id."""


class WorkspaceSettingsError(Exception):
    """The person cannot change this workspace setting. The message says why."""


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
class ChannelOption:
    id: str
    name: str
    is_member: bool


@frozen
class ChannelJoinResult:
    channel_id: str
    error: str | None
