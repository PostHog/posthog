"""The Slack app settings page in PostHog: personal reactions, workspace settings and channel settings.

Who may change what:
- Personal settings: the person, for the Slack user they linked in this workspace.
- Workspace settings: the person who installed Slack, or a project admin.
- Channel settings: anyone who can open the project.
"""

import re
from typing import Any

from posthog.models import User

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.facade.enums import SlackUntaggedMode
from products.slack_app.backend.facade.types import (
    SlackAppSettings,
    SlackChannelSettings,
    SlackPersonalSettings,
    SlackReactionChoice,
    SlackSettingsInvalid,
    SlackWorkspaceSettings,
    WorkspaceSettingsError,
)
from products.slack_app.backend.logic.workspace_setup import can_change_workspace_settings
from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.integration_resolver import accessible_candidates
from products.slack_app.backend.services.reaction_settings import (
    ReactionSettings,
    is_emoji_name,
    load_reactions,
    normalize_emoji_name,
    resolve_reactions,
    save_reactions,
    with_every_kind,
)
from products.slack_app.backend.services.slack_settings import (
    resolve_external_channels_enabled,
    set_external_channels_enabled,
)
from products.slack_app.backend.services.slack_user_oauth import linked_slack_user_id
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, workspace_integrations

# Slack channel IDs: C for public, G for private and older shared channels.
SLACK_CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{2,30}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
# pinned: analytics event name and property values, renaming breaks dashboards
SETTING_CHANGED_EVENT = "slack app setting changed"


def _workspace_id(integration: WorkspaceIntegration) -> str:
    return integration.integration_id or ""


def clean_reactions(reactions: ReactionSettings) -> ReactionSettings:
    """Normalize emoji names. Raises ``SlackSettingsInvalid`` for a name Slack would refuse."""
    cleaned: ReactionSettings = {}
    for kind, choice in reactions.items():
        emoji = normalize_emoji_name(choice.emoji) if choice.emoji is not None else None
        if emoji is not None and not is_emoji_name(emoji):
            raise SlackSettingsInvalid(f"{choice.emoji} is not a Slack emoji name.")
        cleaned[kind] = SlackReactionChoice(emoji=emoji, enabled=choice.enabled)
    return cleaned


def get_settings(integration: WorkspaceIntegration, user: User) -> SlackAppSettings:
    slack_workspace_id = _workspace_id(integration)
    slack_user_id = linked_slack_user_id(user=user, slack_team_id=slack_workspace_id)
    workspace_reactions = load_reactions(slack_workspace_id, None)
    personal_reactions = load_reactions(slack_workspace_id, slack_user_id) if slack_user_id else {}
    return SlackAppSettings(
        integration_id=integration.id,
        slack_workspace_name=((integration.config or {}).get("team") or {}).get("name"),
        can_edit_workspace=can_change_workspace_settings(integration, user),
        workspace=SlackWorkspaceSettings(
            reactions=with_every_kind(workspace_reactions),
            external_channels_enabled=resolve_external_channels_enabled(slack_workspace_id),
        ),
        personal=SlackPersonalSettings(
            slack_user_id=slack_user_id,
            reactions=with_every_kind(personal_reactions),
            effective_reactions=resolve_reactions(workspace_reactions, personal_reactions),
        ),
    )


def update_workspace_settings(
    integration: WorkspaceIntegration,
    user: User,
    *,
    reactions: ReactionSettings | None,
    external_channels_enabled: bool | None,
) -> None:
    if not can_change_workspace_settings(integration, user):
        raise WorkspaceSettingsError(
            "Only the person who installed Slack or a project admin can change these settings."
        )
    slack_workspace_id = _workspace_id(integration)
    if reactions is not None:
        save_reactions(slack_workspace_id, None, clean_reactions(reactions))
        _capture_change(integration, user, scope="workspace", setting="reactions", reactions=reactions)
    if external_channels_enabled is not None:
        set_external_channels_enabled(slack_workspace_id, external_channels_enabled)
        _capture_change(
            integration, user, scope="workspace", setting="external_channels", enabled=external_channels_enabled
        )


def update_personal_settings(integration: WorkspaceIntegration, user: User, *, reactions: ReactionSettings) -> None:
    slack_workspace_id = _workspace_id(integration)
    slack_user_id = linked_slack_user_id(user=user, slack_team_id=slack_workspace_id)
    if slack_user_id is None:
        raise WorkspaceSettingsError("Link your Slack account in this workspace to change your own settings.")
    save_reactions(slack_workspace_id, slack_user_id, clean_reactions(reactions))
    _capture_change(integration, user, scope="personal", setting="reactions", reactions=reactions)


def _channel_settings(row: SlackChannel) -> SlackChannelSettings:
    updated_by = row.updated_by
    return SlackChannelSettings(
        slack_channel_id=row.slack_channel_id,
        default_integration_id=row.default_integration_id,
        default_repository=row.default_repository,
        untagged_question_mode=row.untagged_question_mode,
        updated_by_name=(updated_by.first_name or updated_by.email) if updated_by else None,
        updated_at=row.updated_at,
    )


def list_channel_settings(integration: WorkspaceIntegration) -> tuple[SlackChannelSettings, ...]:
    """Channels with at least one setting. A row that only records an approval is left out."""
    rows = (
        SlackChannel.objects.filter(slack_workspace_id=_workspace_id(integration))
        .exclude(default_integration__isnull=True, default_repository__isnull=True, untagged_question_mode__isnull=True)
        .select_related("updated_by")
        .order_by("slack_channel_id")
    )
    return tuple(_channel_settings(row) for row in rows)


def update_channel_settings(
    integration: WorkspaceIntegration,
    user: User,
    *,
    slack_channel_id: str,
    default_integration_id: int | None,
    default_repository: str | None,
    untagged_question_mode: SlackUntaggedMode | None,
) -> SlackChannelSettings:
    """Replace one channel's settings. A None setting falls back to the workspace or personal setting."""
    if not SLACK_CHANNEL_ID.match(slack_channel_id):
        raise SlackSettingsInvalid(f"{slack_channel_id} is not a Slack channel ID.")
    slack_workspace_id = _workspace_id(integration)
    if default_integration_id is not None:
        options = accessible_candidates(workspace_integrations(slack_workspace_id), user=user)
        if all(option.id != default_integration_id for option in options):
            raise SlackSettingsInvalid("This project is not connected to this Slack workspace, or you can't open it.")
    repository = default_repository.strip() if default_repository else None
    if repository is not None and not REPOSITORY.match(repository):
        raise SlackSettingsInvalid("Enter the repository as owner/name.")

    row, _ = SlackChannel.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=slack_channel_id,
        defaults={
            "default_integration_id": default_integration_id,
            "default_repository": repository,
            "untagged_question_mode": untagged_question_mode.value if untagged_question_mode else None,
            "updated_by": user,
        },
    )
    _capture_change(
        integration,
        user,
        scope="channel",
        setting="channel",
        has_default_project=default_integration_id is not None,
        has_default_repository=repository is not None,
        untagged_question_mode=untagged_question_mode.value if untagged_question_mode else None,
    )
    return _channel_settings(row)


def _capture_change(
    integration: WorkspaceIntegration,
    user: User,
    *,
    scope: str,
    setting: str,
    reactions: ReactionSettings | None = None,
    **props: Any,
) -> None:
    if reactions is not None:
        props["changed_reactions"] = sorted(kind.value for kind in reactions)
    capture_slack_event(integration, SETTING_CHANGED_EVENT, posthog_user=user, scope=scope, setting=setting, **props)
