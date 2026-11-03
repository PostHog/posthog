"""The setup that the installer sees in PostHog on the web after installing the Slack app.

The web asks only for what blocks the Slack app for everyone. All other setup happens later in
Slack. A step that does not apply to the install, or that is already done, is left out, so the
page shows only what is left. Each step computes its status from the database every time and
stores no progress of its own.
"""

from collections.abc import Callable
from functools import cached_property
from urllib.parse import urlencode

from django.db import models

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, User
from posthog.models.integration import Integration
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.services.integration_resolver import accessible_candidates
from products.slack_app.backend.services.slack_settings import (
    resolve_workspace_default_integration_id,
    set_workspace_default_integration,
)

SLACK_APP_REDIRECT_URL = "https://slack.com/app_redirect"


class SlackSetupStepKey(models.TextChoices):
    AI_CONSENT = "ai_consent", "AI data processing"
    DEFAULT_PROJECT = "default_project", "Default project"


class DefaultProjectError(Exception):
    """The person cannot set this project as the workspace default."""


@frozen(slots=False)
class SetupContext:
    integration: Integration
    user: User

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


def _ai_consent_applies(ctx: SetupContext) -> bool:
    return not ctx.integration.team.organization.is_ai_data_processing_approved


def _default_project_applies(ctx: SetupContext) -> bool:
    return len(ctx.project_options) >= 2


def _default_project_is_done(ctx: SetupContext) -> bool:
    return resolve_workspace_default_integration_id(ctx.slack_workspace_id) is not None


# Ordered by priority: a step that blocks every answer in Slack comes first.
SETUP_STEPS: tuple[SetupStep, ...] = (
    SetupStep(key=SlackSetupStepKey.AI_CONSENT, applies=_ai_consent_applies, is_done=lambda _: False),
    SetupStep(
        key=SlackSetupStepKey.DEFAULT_PROJECT, applies=_default_project_applies, is_done=_default_project_is_done
    ),
)


def open_slack_url(integration: Integration) -> str | None:
    """A link that opens the app's direct message in the installer's Slack workspace."""
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"{SLACK_APP_REDIRECT_URL}?{urlencode({'app': app_id, 'team': integration.integration_id})}"


def get_workspace_setup(integration: Integration, user: User) -> WorkspaceSetup:
    ctx = SetupContext(integration=integration, user=user)
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


def _can_set_workspace_default(integration: Integration, user: User) -> bool:
    # The workspace default changes routing for everyone in the Slack workspace, so only the
    # person who installed it or an admin of its project may set it from the web.
    if integration.created_by_id == user.id:
        return True
    level = UserPermissions(user=user).team(integration.team).effective_membership_level
    return level is not None and level >= OrganizationMembership.Level.ADMIN


def set_default_project(integration: Integration, user: User, target_integration_id: int) -> None:
    if not _can_set_workspace_default(integration, user):
        raise DefaultProjectError("Only the person who installed Slack or a project admin can set the default project.")
    ctx = SetupContext(integration=integration, user=user)
    target = next((option for option in ctx.project_options if option.id == target_integration_id), None)
    if target is None:
        raise DefaultProjectError("This project is not connected to this Slack workspace, or you can't open it.")
    set_workspace_default_integration(ctx.slack_workspace_id, target)
