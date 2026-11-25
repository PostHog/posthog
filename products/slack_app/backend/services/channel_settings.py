"""Read the channel settings that each organization sets on the web, stored on ``SlackChannelSettings``.

A Slack workspace can connect to projects in several organizations, and each organization keeps its own row.
The settings apply only while the ``slack-app-web-settings`` flag is on for the organization of the project in
question. Rows are read first, so the flag is checked only for a channel that has a setting.

- Project: a row's default project wins over the personal and workspace defaults, for an author who can open it.
- Repository and question mode: the row of the organization that owns the routed project.
- Question mode: the stricter of the author's own mode and the channel's, so a channel never opts a person in.
"""

from posthog.dataclasses import frozen

from products.slack_app.backend.feature_flags import is_slack_app_web_settings_enabled
from products.slack_app.backend.models import SlackChannelSettings, UntaggedFollowupMode
from products.slack_app.backend.services.integration_references import read_integration_id
from products.slack_app.backend.services.slack_settings import resolve_untagged_question_mode
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

STRICTNESS = {UntaggedFollowupMode.AUTO: 0, UntaggedFollowupMode.ASK: 1, UntaggedFollowupMode.NEVER: 2}


def channel_default_integration_ids(slack_workspace_id: str, slack_channel_id: str | None) -> list[int]:
    """The default projects that organizations set for this channel, oldest setting first."""
    if not slack_workspace_id or not slack_channel_id:
        return []
    references = (
        SlackChannelSettings.objects.filter(
            slack_workspace_id=slack_workspace_id,
            slack_channel_id=slack_channel_id,
            default_integration_id__isnull=False,
        )
        .order_by("created_at")
        .values_list("default_integration_id", flat=True)
    )
    return [integration_id for integration_id in map(read_integration_id, references) if integration_id is not None]


@frozen
class _OrganizationChannelRow:
    default_repository: str | None = None
    untagged_question_mode: str | None = None


def _organization_row(integration: WorkspaceIntegration, slack_channel_id: str | None) -> _OrganizationChannelRow:
    if not slack_channel_id:
        return _OrganizationChannelRow()
    row = (
        SlackChannelSettings.objects.filter(
            slack_workspace_id=integration.integration_id or "",
            slack_channel_id=slack_channel_id,
            organization_id=integration.team.organization_id,
        )
        .values("default_repository", "untagged_question_mode")
        .first()
    )
    return _OrganizationChannelRow(**row) if row is not None else _OrganizationChannelRow()


def channel_default_repository(integration: WorkspaceIntegration, slack_channel_id: str | None) -> str | None:
    repository = _organization_row(integration, slack_channel_id).default_repository
    if repository is None or not is_slack_app_web_settings_enabled(integration):
        return None
    return repository


def resolve_channel_untagged_question_mode(
    integration: WorkspaceIntegration, slack_user_id: str | None, slack_channel_id: str | None
) -> UntaggedFollowupMode:
    """The author's own mode, made stricter by the channel's mode for the organization of ``integration``."""
    personal = resolve_untagged_question_mode(integration.integration_id or "", slack_user_id)
    if not slack_user_id or personal == UntaggedFollowupMode.NEVER:
        return personal
    stored = _organization_row(integration, slack_channel_id).untagged_question_mode
    if stored not in UntaggedFollowupMode.values or not is_slack_app_web_settings_enabled(integration):
        return personal
    channel = UntaggedFollowupMode(stored)
    return channel if STRICTNESS[channel] > STRICTNESS[personal] else personal
