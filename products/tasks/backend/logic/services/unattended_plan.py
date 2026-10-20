"""Whether a run that no client starts, such as one from the Slack app, can bill to the user's own plan.

Desktop and the web composer send `{adapter}_model_access` with every run they create. A surface
with no client in the loop has no such choice to send, so a connected plan counts as the opt-in.
"""

from typing import cast, get_args

from posthog.models.integration.codex import STATUS_CONNECTED, CodexUserIntegration
from posthog.models.user import User

from products.tasks.backend.constants import SUBSCRIPTION_PLAN_NAMES
from products.tasks.backend.facade.contracts import UnattendedPlanStatus
from products.tasks.backend.feature_flags import own_subscription_cloud_enabled
from products.tasks.backend.logic.model_access import SubscriptionAdapter


def _plan_connected(user: User, adapter: SubscriptionAdapter) -> bool:
    """A Claude plan never counts, because PostHog stores no Claude token: the owner's Desktop must
    answer the token request each time an agent session starts. PostHog holds the ChatGPT token and
    refreshes it for the sandbox, so a ChatGPT plan can run without the user.
    """
    if adapter != "codex":
        return False
    integration = CodexUserIntegration.for_user(user.id)
    return integration is not None and integration.status == STATUS_CONNECTED


def unattended_plan_status(
    user: User, adapter: SubscriptionAdapter, *, organization_id: str
) -> UnattendedPlanStatus | None:
    """The user's plan for unattended runs, or `None` when it is not offered to them."""
    if adapter != "codex":
        return None
    if not own_subscription_cloud_enabled(adapter, distinct_id=user.distinct_id, organization_id=organization_id):
        return None
    return UnattendedPlanStatus(plan_name=SUBSCRIPTION_PLAN_NAMES[adapter], connected=_plan_connected(user, adapter))


def unattended_model_access_state(user: User, *, organization_id: str, runtime_adapter: str | None) -> dict[str, str]:
    """The run-state keys that put a new run on the user's plan, or none to keep it on PostHog credits.

    The plan must match the run's harness, because `resolve_model_access` refuses a ChatGPT plan
    on a Claude run. `Task.create_run` then records the acting user as the plan owner. The local
    connection check runs before the remote flag check, so most mentions cost no flag request.
    """
    if runtime_adapter not in get_args(SubscriptionAdapter):
        return {}
    adapter = cast(SubscriptionAdapter, runtime_adapter)
    if not _plan_connected(user, adapter):
        return {}
    if not own_subscription_cloud_enabled(adapter, distinct_id=user.distinct_id, organization_id=organization_id):
        return {}
    return {f"{adapter}_model_access": "own-subscription"}
