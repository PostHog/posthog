"""The Slack app settings page in PostHog: personal reactions, workspace settings and channel settings.

Who may change what:
- Personal settings: the person, for the Slack user they linked in this workspace.
- Workspace settings: the person who installed Slack, or a project admin.
- Channel settings: anyone who can open the project.
"""

import re
from typing import Any
from uuid import UUID

from django.db.models import Q

from posthog.models import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.facade.enums import SlackChannelQuestionMode
from products.slack_app.backend.facade.types import (
    UNSET,
    ProjectOption,
    SlackAppSettings,
    SlackChannelSettings,
    SlackPersonalSettings,
    SlackPersonalSettingsChange,
    SlackReactionChoice,
    SlackRepositoryOptions,
    SlackSettingsInvalid,
    SlackWorkspaceSettings,
    WorkspaceSettingsError,
)
from products.slack_app.backend.logic.feature_tips.state import parse_state, set_tips_enabled
from products.slack_app.backend.logic.workspace_setup import can_change_workspace_settings
from products.slack_app.backend.models import (
    SlackChannelSettings as SlackChannelSettingsRow,
    SlackSettings as SlackSettingsRow,
    ThreadJoinMode,
    UntaggedFollowupMode,
)
from products.slack_app.backend.services.integration_references import read_integration_id, store_integration_id
from products.slack_app.backend.services.integration_resolver import accessible_candidates
from products.slack_app.backend.services.reaction_settings import (
    ReactionSettings,
    is_emoji_name,
    normalize_emoji_name,
    parse_reactions,
    resolve_reactions,
    save_reactions,
    with_every_kind,
)
from products.slack_app.backend.services.slack_settings import (
    mode_from_stored,
    resolve_external_channels_enabled,
    set_auto_model_choice,
    set_external_channels_enabled,
    set_personal_default_integration,
    set_thread_join_mode,
    set_untagged_followup_mode,
    set_untagged_question_mode,
)
from products.slack_app.backend.services.slack_user_oauth import linked_slack_user_id
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, workspace_integrations

# Slack channel IDs: C for public, G for private and older shared channels.
SLACK_CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{2,30}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
# Every Slack message reads the channel rows, and the settings page lists them all on one page.
MAX_CHANNEL_SETTINGS = 200
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


def _project_options(integration: WorkspaceIntegration, user: User) -> list[WorkspaceIntegration]:
    """Projects connected to this Slack workspace that the person can open."""
    return accessible_candidates(workspace_integrations(_workspace_id(integration)), user=user)


# The columns the settings page shows, read from the workspace row and the person's row in one query.
_SETTINGS_COLUMNS = (
    "slack_user_id",
    "reactions",
    "default_integration_id",
    "untagged_followup_mode",
    "untagged_question_mode",
    "thread_join_mode",
    "auto_model_choice",
    "feature_tips",
)


def _settings_rows(slack_workspace_id: str, slack_user_id: str | None) -> dict[str | None, dict[str, Any]]:
    """The stored workspace row and personal row, keyed by Slack user ID. The workspace row has the key None."""
    rows = Q(slack_user_id__isnull=True)
    if slack_user_id:
        rows |= Q(slack_user_id=slack_user_id)
    return {
        row["slack_user_id"]: row
        for row in SlackSettingsRow.objects.filter(rows, slack_workspace_id=slack_workspace_id).values(
            *_SETTINGS_COLUMNS
        )
    }


def _personal_settings(
    integration: WorkspaceIntegration,
    user: User,
    slack_user_id: str | None,
    workspace_reactions: ReactionSettings,
    personal_row: dict[str, Any],
) -> SlackPersonalSettings:
    """Resolves each value the way the Slack resolvers in `slack_settings` do, from a row read once."""
    personal_reactions = parse_reactions(personal_row.get("reactions"))

    def untagged_mode(column: str) -> UntaggedFollowupMode:
        if not slack_user_id:
            return UntaggedFollowupMode.NEVER
        return mode_from_stored(
            personal_row.get(column),
            UntaggedFollowupMode,
            unset=UntaggedFollowupMode.ASK,
            unknown=UntaggedFollowupMode.NEVER,
        )

    thread_join_mode = (
        mode_from_stored(
            personal_row.get("thread_join_mode"),
            ThreadJoinMode,
            unset=ThreadJoinMode.ALLOW,
            unknown=ThreadJoinMode.NEVER,
        )
        if slack_user_id
        else ThreadJoinMode.ALLOW
    )
    return SlackPersonalSettings(
        slack_user_id=slack_user_id,
        reactions=with_every_kind(personal_reactions),
        effective_reactions=resolve_reactions(workspace_reactions, personal_reactions),
        default_integration_id=personal_row.get("default_integration_id"),
        project_options=tuple(
            ProjectOption(
                integration_id=option.id,
                project_name=option.team.name,
                organization_name=option.team.organization.name,
            )
            for option in _project_options(integration, user)
        ),
        untagged_followup_mode=untagged_mode("untagged_followup_mode").value,
        untagged_question_mode=untagged_mode("untagged_question_mode").value,
        thread_join_mode=thread_join_mode.value,
        auto_model_choice=bool(personal_row.get("auto_model_choice")),
        feature_tips_enabled=parse_state(personal_row.get("feature_tips")).opted_out_at is None,
    )


def get_settings(integration: WorkspaceIntegration, user: User) -> SlackAppSettings:
    slack_workspace_id = _workspace_id(integration)
    slack_user_id = linked_slack_user_id(user=user, slack_team_id=slack_workspace_id)
    rows = _settings_rows(slack_workspace_id, slack_user_id)
    workspace_reactions = parse_reactions(rows.get(None, {}).get("reactions"))
    personal_row = rows.get(slack_user_id, {}) if slack_user_id else {}
    return SlackAppSettings(
        integration_id=integration.id,
        slack_workspace_name=((integration.config or {}).get("team") or {}).get("name"),
        can_edit_workspace=can_change_workspace_settings(integration, user),
        workspace=SlackWorkspaceSettings(
            reactions=with_every_kind(workspace_reactions),
            external_channels_enabled=resolve_external_channels_enabled(slack_workspace_id),
        ),
        personal=_personal_settings(integration, user, slack_user_id, workspace_reactions, personal_row),
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


def update_personal_settings(
    integration: WorkspaceIntegration, user: User, change: SlackPersonalSettingsChange
) -> None:
    slack_workspace_id = _workspace_id(integration)
    slack_user_id = linked_slack_user_id(user=user, slack_team_id=slack_workspace_id)
    if slack_user_id is None:
        raise WorkspaceSettingsError("Link your Slack account in this workspace to change your own settings.")
    if change.default_integration_id is not UNSET and change.default_integration_id is not None:
        if all(option.id != change.default_integration_id for option in _project_options(integration, user)):
            raise SlackSettingsInvalid("This project is not connected to this Slack workspace, or you can't open it.")

    if change.reactions is not UNSET:
        save_reactions(slack_workspace_id, slack_user_id, clean_reactions(change.reactions))
        _capture_change(integration, user, scope="personal", setting="reactions", reactions=change.reactions)
    if change.default_integration_id is not UNSET:
        set_personal_default_integration(slack_workspace_id, slack_user_id, change.default_integration_id)
        _capture_change(
            integration,
            user,
            scope="personal",
            setting="default_project",
            uses_workspace_default=change.default_integration_id is None,
        )
    if change.untagged_followup_mode is not UNSET:
        set_untagged_followup_mode(
            slack_workspace_id, slack_user_id, UntaggedFollowupMode(change.untagged_followup_mode)
        )
        _capture_change(
            integration, user, scope="personal", setting="untagged_replies", value=change.untagged_followup_mode
        )
    if change.untagged_question_mode is not UNSET:
        set_untagged_question_mode(
            slack_workspace_id, slack_user_id, UntaggedFollowupMode(change.untagged_question_mode)
        )
        _capture_change(
            integration, user, scope="personal", setting="untagged_questions", value=change.untagged_question_mode
        )
    if change.thread_join_mode is not UNSET:
        set_thread_join_mode(slack_workspace_id, slack_user_id, ThreadJoinMode(change.thread_join_mode))
        _capture_change(integration, user, scope="personal", setting="thread_join", value=change.thread_join_mode)
    if change.auto_model_choice is not UNSET:
        set_auto_model_choice(slack_workspace_id, slack_user_id, change.auto_model_choice)
        _capture_change(
            integration, user, scope="personal", setting="auto_model_choice", enabled=change.auto_model_choice
        )
    if change.feature_tips_enabled is not UNSET:
        set_tips_enabled(slack_workspace_id, slack_user_id, change.feature_tips_enabled)
        _capture_change(
            integration, user, scope="personal", setting="feature_tips", enabled=change.feature_tips_enabled
        )


def _organization_id(integration: WorkspaceIntegration) -> UUID:
    return integration.team.organization_id


def _channel_settings(row: SlackChannelSettingsRow) -> SlackChannelSettings:
    return SlackChannelSettings(
        slack_channel_id=row.slack_channel_id,
        default_integration_id=read_integration_id(row.default_integration_id),
        default_repository=row.default_repository,
        untagged_question_mode=row.untagged_question_mode,
        updated_by_name=row.updated_by.first_name or None if row.updated_by else None,
        updated_at=row.updated_at,
    )


def list_repository_options(integration: WorkspaceIntegration, user: User) -> SlackRepositoryOptions:
    from products.slack_app.backend.api import (  # noqa: PLC0415 — api.py imports the services this module uses
        _get_full_repo_names,
    )

    return SlackRepositoryOptions(
        repositories=tuple(sorted(_get_full_repo_names(integration, user_id=user.id), key=str.lower)),
        github_connected=UserIntegration.objects.filter(
            user=user, kind=UserIntegration.IntegrationKind.GITHUB
        ).exists(),
    )


def list_channel_settings(integration: WorkspaceIntegration) -> tuple[SlackChannelSettings, ...]:
    """The channel settings of the install's organization. Other organizations in the workspace keep their own."""
    rows = (
        SlackChannelSettingsRow.objects.filter(
            slack_workspace_id=_workspace_id(integration), organization_id=_organization_id(integration)
        )
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
    untagged_question_mode: SlackChannelQuestionMode | None,
) -> SlackChannelSettings:
    """Replace the organization's settings for one channel. Clearing every setting removes the row."""
    if not SLACK_CHANNEL_ID.match(slack_channel_id):
        raise SlackSettingsInvalid(f"{slack_channel_id} is not a Slack channel ID.")
    slack_workspace_id = _workspace_id(integration)
    organization_id = _organization_id(integration)
    if default_integration_id is not None:
        if all(
            option.id != default_integration_id or option.team.organization_id != organization_id
            for option in _project_options(integration, user)
        ):
            raise SlackSettingsInvalid(
                "Pick a project of this organization that is connected to this Slack workspace and that you can open."
            )
    repository = default_repository.strip() if default_repository else None
    if repository is not None and not REPOSITORY.match(repository):
        raise SlackSettingsInvalid("Enter the repository as owner/name.")

    lookup: dict[str, Any] = {
        "slack_workspace_id": slack_workspace_id,
        "slack_channel_id": slack_channel_id,
        "organization_id": organization_id,
    }
    if default_integration_id is None and repository is None and untagged_question_mode is None:
        SlackChannelSettingsRow.objects.filter(**lookup).delete()
        result = SlackChannelSettings(
            slack_channel_id=slack_channel_id,
            default_integration_id=None,
            default_repository=None,
            untagged_question_mode=None,
            updated_by_name=None,
            updated_at=None,
        )
    else:
        if (
            not SlackChannelSettingsRow.objects.filter(**lookup).exists()
            and SlackChannelSettingsRow.objects.filter(
                slack_workspace_id=slack_workspace_id, organization_id=organization_id
            ).count()
            >= MAX_CHANNEL_SETTINGS
        ):
            raise SlackSettingsInvalid(
                f"Up to {MAX_CHANNEL_SETTINGS} channels can have their own settings. Remove one to add another."
            )
        row, _ = SlackChannelSettingsRow.objects.update_or_create(
            **lookup,
            defaults={
                "default_integration_id": store_integration_id(default_integration_id),
                "default_repository": repository,
                "untagged_question_mode": untagged_question_mode.value if untagged_question_mode else None,
                "updated_by": user,
            },
        )
        result = _channel_settings(row)
    _capture_change(
        integration,
        user,
        scope="channel",
        setting="channel",
        has_default_project=default_integration_id is not None,
        has_default_repository=repository is not None,
        untagged_question_mode=untagged_question_mode.value if untagged_question_mode else None,
    )
    return result


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
