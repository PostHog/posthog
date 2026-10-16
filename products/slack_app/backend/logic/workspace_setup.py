"""Workspace setup that runs in PostHog on the web after someone installs the Slack app.

Each step owns one workspace or project setting. A step that does not apply to the install, or
that is already done, is left out of the state, so the page shows only what is left to do. Steps
compute their status from the database every time and store no progress of their own.
"""

from collections.abc import Callable
from urllib.parse import urlencode

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.models.integration import Integration

SLACK_APP_REDIRECT_URL = "https://slack.com/app_redirect"


@frozen
class SetupContext:
    integration: Integration
    user: User


@frozen
class SetupStep:
    key: str
    applies: Callable[[SetupContext], bool]
    is_done: Callable[[SetupContext], bool]


@frozen
class WorkspaceSetup:
    integration_id: int
    slack_workspace_name: str | None
    open_slack_url: str | None
    steps: tuple[str, ...]


# Steps run in this order. Each step lives in its own module and is added here.
SETUP_STEPS: tuple[SetupStep, ...] = ()


def open_slack_url(integration: Integration) -> str | None:
    """A link that opens the app's direct message in the installer's Slack workspace."""
    app_id = (integration.config or {}).get("app_id")
    if not app_id or not integration.integration_id:
        return None
    return f"{SLACK_APP_REDIRECT_URL}?{urlencode({'app': app_id, 'team': integration.integration_id})}"


def get_workspace_setup(integration: Integration, user: User) -> WorkspaceSetup:
    context = SetupContext(integration=integration, user=user)
    return WorkspaceSetup(
        integration_id=integration.id,
        slack_workspace_name=((integration.config or {}).get("team") or {}).get("name"),
        open_slack_url=open_slack_url(integration),
        steps=tuple(step.key for step in SETUP_STEPS if step.applies(context) and not step.is_done(context)),
    )
