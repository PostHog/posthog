"""The setup that the installer sees in PostHog on the web after installing the Slack app.

The web asks only for what blocks the Slack app for everyone, plus a few steps that work better in
a browser when the person started the install on the Slack page in PostHog. All other setup
happens later in Slack. A step that does not apply to the install, or that is already done, is left
out, so the page shows only what is left. Each step computes its status from the database every
time and stores no progress of its own.
"""

from collections.abc import Callable
from functools import cached_property
from urllib.parse import urlencode

from django.db import models

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.slack.channels import SHARED_CHANNEL_FLAGS, join_channel
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.services.integration_resolver import accessible_candidates
from products.slack_app.backend.services.slack_scopes import has_scopes
from products.slack_app.backend.services.slack_settings import (
    resolve_workspace_default_integration_id,
    set_workspace_default_integration,
)

SLACK_APP_REDIRECT_URL = "https://slack.com/app_redirect"
CHANNELS_JOIN_SCOPE = "channels:join"
# Slack rate limits conversations.join, and a long list in one request would hold the request open.
MAX_CHANNELS_TO_JOIN = 20


class SlackSetupStepKey(models.TextChoices):
    AI_CONSENT = "ai_consent", "AI data processing"
    DEFAULT_PROJECT = "default_project", "Default project"
    CHANNELS = "channels", "Channels"


class SlackSetupEntry(models.TextChoices):
    SLACK_PAGE = "slack_page", "The Slack page in PostHog"
    OTHER = "other", "Another place, such as a channel picker"


class WorkspaceSettingsError(Exception):
    """The person cannot change this workspace setting."""


@frozen(slots=False)
class SetupContext:
    integration: Integration
    user: User
    entry: SlackSetupEntry

    @property
    def slack_workspace_id(self) -> str:
        return self.integration.integration_id or ""

    @cached_property
    def project_options(self) -> list[Integration]:
        """Projects connected to this Slack workspace that the person can open, oldest install first."""
        installs = (
            Integration.objects.filter(kind="slack", integration_id=self.slack_workspace_id)
            .select_related("team", "team__organization")
            .order_by("id")
        )
        return accessible_candidates(installs, user=self.user)


@frozen
class SetupStep:
    key: SlackSetupStepKey
    applies: Callable[[SetupContext], bool]
    is_done: Callable[[SetupContext], bool]


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


@frozen
class ChannelOption:
    id: str
    name: str
    is_member: bool


@frozen
class ChannelJoinResult:
    channel_id: str
    error: str | None


def _ai_consent_applies(ctx: SetupContext) -> bool:
    return not ctx.integration.team.organization.is_ai_data_processing_approved


def _default_project_applies(ctx: SetupContext) -> bool:
    return len(ctx.project_options) >= 2


def _default_project_is_done(ctx: SetupContext) -> bool:
    return resolve_workspace_default_integration_id(ctx.slack_workspace_id) is not None


def _channels_applies(ctx: SetupContext) -> bool:
    # A person who started on the Slack page is setting up the Slack app on purpose. Someone who
    # connected Slack from a channel picker is in the middle of another task.
    return ctx.entry == SlackSetupEntry.SLACK_PAGE and has_scopes(ctx.integration, [CHANNELS_JOIN_SCOPE])


def _never_done(_: SetupContext) -> bool:
    return False


# Ordered by priority: a step that blocks every answer in Slack comes first.
SETUP_STEPS: tuple[SetupStep, ...] = (
    SetupStep(key=SlackSetupStepKey.AI_CONSENT, applies=_ai_consent_applies, is_done=_never_done),
    SetupStep(
        key=SlackSetupStepKey.DEFAULT_PROJECT, applies=_default_project_applies, is_done=_default_project_is_done
    ),
    SetupStep(key=SlackSetupStepKey.CHANNELS, applies=_channels_applies, is_done=_never_done),
)


def open_slack_url(integration: Integration) -> str | None:
    """A link that opens the app's direct message in the installer's Slack workspace."""
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"{SLACK_APP_REDIRECT_URL}?{urlencode({'app': app_id, 'team': integration.integration_id})}"


def get_workspace_setup(integration: Integration, user: User, entry: SlackSetupEntry) -> WorkspaceSetup:
    ctx = SetupContext(integration=integration, user=user, entry=entry)
    steps = tuple(step.key for step in SETUP_STEPS if step.applies(ctx) and not step.is_done(ctx))
    return WorkspaceSetup(
        integration_id=integration.id,
        slack_workspace_name=((integration.config or {}).get("team") or {}).get("name"),
        open_slack_url=open_slack_url(integration),
        steps=steps,
        project_options=tuple(
            ProjectOption(
                integration_id=option.id,
                project_name=option.team.name,
                organization_name=option.team.organization.name,
            )
            for option in ctx.project_options
        )
        if SlackSetupStepKey.DEFAULT_PROJECT in steps
        else (),
    )


def _can_change_workspace_settings(integration: Integration, user: User) -> bool:
    # These settings change the Slack workspace for everyone in it, so only the person who
    # installed it or an admin of its project may change them from the web.
    if integration.created_by_id == user.id:
        return True
    level = UserPermissions(user=user).team(integration.team).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def set_default_project(integration: Integration, user: User, target_integration_id: int) -> None:
    if not _can_change_workspace_settings(integration, user):
        raise WorkspaceSettingsError(
            "Only the person who installed Slack or a project admin can set the default project."
        )
    ctx = SetupContext(integration=integration, user=user, entry=SlackSetupEntry.OTHER)
    target = next((option for option in ctx.project_options if option.id == target_integration_id), None)
    if target is None:
        raise WorkspaceSettingsError("This project is not connected to this Slack workspace, or you can't open it.")
    set_workspace_default_integration(ctx.slack_workspace_id, target)


def list_channel_options(integration: Integration) -> tuple[ChannelOption, ...]:
    """Public channels that the bot can join. Shared channels are left out, because people outside
    the workspace would see the bot there."""
    channels = SlackIntegration(integration).list_public_channels()
    return tuple(
        ChannelOption(id=channel["id"], name=channel["name"], is_member=bool(channel.get("is_member")))
        for channel in channels
        if not any(channel.get(flag) for flag in SHARED_CHANNEL_FLAGS)
    )


def join_channels(
    integration: Integration, user: User, channel_ids: list[str], *, post_welcome: bool
) -> tuple[ChannelJoinResult, ...]:
    from products.slack_app.backend.api import (  # noqa: PLC0415 — api.py imports the services this module uses
        release_channel_welcome_skip,
        skip_channel_welcome,
    )

    if not _can_change_workspace_settings(integration, user):
        raise WorkspaceSettingsError(
            "Only the person who installed Slack or a project admin can add PostHog to channels."
        )
    if not has_scopes(integration, [CHANNELS_JOIN_SCOPE]):
        raise WorkspaceSettingsError("This Slack install can't join channels. Invite PostHog with /invite @PostHog.")

    # The ids come from the browser, so only channels from the same list the page showed are joined.
    allowed = {option.id for option in list_channel_options(integration)}
    slack = SlackIntegration(integration)
    slack_workspace_id = integration.integration_id or ""
    results: list[ChannelJoinResult] = []
    for channel_id in dict.fromkeys(channel_ids):
        if channel_id not in allowed:
            results.append(ChannelJoinResult(channel_id=channel_id, error="channel_not_available"))
            continue
        if not post_welcome:
            skip_channel_welcome(slack_workspace_id, channel_id)
        error = join_channel(slack, channel_id)
        if error is not None and not post_welcome:
            release_channel_welcome_skip(slack_workspace_id, channel_id)
        results.append(ChannelJoinResult(channel_id=channel_id, error=error))
    return tuple(results)
