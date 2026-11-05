from collections.abc import Callable
from enum import StrEnum
from functools import cached_property

from posthog.dataclasses import frozen
from posthog.models import User
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.services.onboarding_checks import is_org_admin
from products.slack_app.backend.services.slack_app_home import linked_posthog_user
from products.slack_app.backend.services.slack_user_info import is_slack_workspace_admin
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration


class OnboardingStepKey(StrEnum):
    # pinned: analytics property values and stored skip keys, renaming breaks both
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
    def is_workspace_admin(self) -> bool:
        """The person who installed the app, or a Slack workspace admin or owner."""
        installer = ((self.integration.config or {}).get("authed_user") or {}).get("id")
        if installer == self.slack_user_id:
            return True
        return is_slack_workspace_admin(SlackIntegration(self.integration), self.integration, self.slack_user_id)

    @cached_property
    def is_org_admin(self) -> bool:
        user = self.posthog_user
        return user is not None and is_org_admin(user.id, self.integration.team_id)


@frozen
class OnboardingStepSpec:
    """``applies`` and ``is_done`` read the database on every plan, so done status is never stored."""

    key: OnboardingStepKey
    title: str
    done_text: str
    skippable: bool
    applies: Callable[[OnboardingContext], bool]
    is_done: Callable[[OnboardingContext], bool]
    render: Callable[[OnboardingContext], list[dict]]
