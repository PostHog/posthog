"""Read the settings that people set for one Slack channel on the web, stored on ``SlackChannel``.

A channel setting wins over the personal and workspace settings. It applies only while the
``slack-app-web-settings`` flag is on for the workspace's organization. The row is read first, so
the flag is checked only for a channel that has a setting.
"""

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationRecord

from products.slack_app.backend.feature_flags import is_slack_app_web_settings_enabled
from products.slack_app.backend.models import SlackChannel, UntaggedFollowupMode
from products.slack_app.backend.services.integration_references import read_integration_id
from products.slack_app.backend.services.slack_settings import resolve_untagged_question_mode


@frozen
class ChannelDefaults:
    default_integration_id: int | None
    default_repository: str | None
    untagged_question_mode: UntaggedFollowupMode | None


def load_channel_defaults(slack_workspace_id: str, slack_channel_id: str | None) -> ChannelDefaults | None:
    if not slack_workspace_id or not slack_channel_id:
        return None
    row = (
        SlackChannel.objects.filter(slack_workspace_id=slack_workspace_id, slack_channel_id=slack_channel_id)
        .values_list("default_integration_id", "default_repository", "untagged_question_mode")
        .first()
    )
    if row is None:
        return None
    default_integration_id, default_repository, mode = row
    return ChannelDefaults(
        default_integration_id=read_integration_id(default_integration_id),
        default_repository=default_repository,
        untagged_question_mode=UntaggedFollowupMode(mode) if mode in UntaggedFollowupMode.values else None,
    )


def resolve_channel_untagged_question_mode(
    flag_integration: IntegrationRecord, slack_user_id: str | None, slack_channel_id: str | None
) -> UntaggedFollowupMode:
    """The channel's mode when it has one, otherwise the author's own mode."""
    slack_workspace_id = flag_integration.integration_id or ""
    defaults = load_channel_defaults(slack_workspace_id, slack_channel_id)
    if (
        slack_user_id
        and defaults is not None
        and defaults.untagged_question_mode is not None
        and is_slack_app_web_settings_enabled(flag_integration)
    ):
        return defaults.untagged_question_mode
    return resolve_untagged_question_mode(slack_workspace_id, slack_user_id)
