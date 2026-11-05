import json
from enum import StrEnum
from functools import cached_property
from typing import Any

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_oauth_enabled
from products.slack_app.backend.onboarding import installer_slack_user_id
from products.slack_app.backend.services.onboarding_checks import is_org_admin
from products.slack_app.backend.services.slack_app_home import linked_posthog_user
from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

# pinned: analytics event name, renaming breaks dashboards
STEP_COMPLETED_EVENT = "slack app onboarding step completed"


class OnboardingStepKey(StrEnum):
    # pinned: analytics property values and stored step keys, renaming breaks both
    LINK_ACCOUNT = "link_account"
    AI_CONSENT = "ai_consent"
    GITHUB = "github"
    INBOX_CHANNEL = "inbox_channel"
    SOURCES = "sources"
    MODEL = "model"
    REPLIES_IN_THREADS = "replies_in_threads"


@frozen(slots=False)
class OnboardingContext:
    """Each check runs at most once per plan, because several steps ask the same question."""

    integration: WorkspaceIntegration
    slack_user_id: str

    @cached_property
    def posthog_user(self) -> User | None:
        return linked_posthog_user(self.integration, self.slack_user_id)

    @cached_property
    def can_link(self) -> bool:
        """Whether the person has, or can get, a linked PostHog account."""
        return self.posthog_user is not None or is_slack_app_oauth_enabled(self.integration)

    @cached_property
    def is_workspace_admin(self) -> bool:
        """The person who installed the app, or a Slack workspace admin or owner."""
        if installer_slack_user_id(self.integration) == self.slack_user_id:
            return True
        return is_slack_workspace_admin(SlackIntegration(self.integration), self.integration, self.slack_user_id)

    @cached_property
    def is_org_admin(self) -> bool:
        user = self.posthog_user
        return user is not None and is_org_admin(user.id, self.integration.team_id)


def read_action_value(action: dict[str, Any]) -> dict[str, Any] | None:
    raw = action.get("value") or (action.get("selected_option") or {}).get("value")
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


@frozen
class StepClick:
    """What a click on a step button did. The person gets ``message`` as a reply that only they see."""

    message: str | None = None
    # A tick on a signal checkbox saves at once but keeps the step open, so the person can tick more.
    refresh: bool = True


class OnboardingStep:
    """One step of the onboarding thread. The thread decides the steps when it starts, from ``applies`` and
    ``is_done``. It asks both again on every refresh, so it never stores whether a step is done.

    ``applies`` must not depend on the account link: the link is the first step, and the thread promises
    the person a number of steps before they link."""

    key: OnboardingStepKey
    title: str
    done_text: str
    skippable: bool = True
    # The buttons that ``apply_action`` handles. Skip and Continue are the same for each step.
    action_ids: frozenset[str] = frozenset()

    def applies(self, ctx: OnboardingContext) -> bool:
        return True

    def is_done(self, ctx: OnboardingContext) -> bool:
        raise NotImplementedError

    def render(self, ctx: OnboardingContext) -> list[dict]:
        raise NotImplementedError

    def handles(self, action_id: str) -> bool:
        return action_id in self.action_ids

    def read_value(self, action: dict[str, Any]) -> dict[str, Any] | None:
        return read_action_value(action)

    def apply_action(self, ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
        raise NotImplementedError

    def record_completed(self, ctx: OnboardingContext, *, choice: str | None = None, model: str | None = None) -> None:
        capture_slack_event(
            ctx.integration,
            STEP_COMPLETED_EVENT,
            slack_user_id=ctx.slack_user_id,
            step=self.key,
            choice=choice,
            model=model,
        )
