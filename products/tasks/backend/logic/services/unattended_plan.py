"""Whether a run that no client starts, such as one from the Slack app, can bill to the user's own plan.

Desktop and the web composer send `{adapter}_model_access` with every run they create. A surface
with no client in the loop has no such choice to send, so a connected plan counts as the opt-in.
The caller checks the plan's rollout flag (`own_subscription_cloud_enabled`) first, because a run
marked for a plan whose rollout is off fails when it starts instead of falling back to credits.
"""

from typing import cast, get_args

from posthog.models.integration.codex import CodexUserIntegration
from posthog.models.user import User

from products.tasks.backend.logic.model_access import SubscriptionAdapter


def can_bill_plan_unattended(user: User, adapter: SubscriptionAdapter) -> bool:
    """Whether the user's plan for this adapter can pay for a run while the user is not at a client.

    A Claude plan cannot, because PostHog stores no Claude token: the owner's Desktop must answer
    the token request each time an agent session starts. A ChatGPT plan can, because PostHog
    holds the token and refreshes it for the sandbox.
    """
    if adapter != "codex":
        return False
    integration = CodexUserIntegration.for_user(user.id)
    return integration is not None and integration.is_connected()


def unattended_model_access_state(user: User, *, runtime_adapter: str | None) -> dict[str, str]:
    """The run-state keys that put a new run on the user's plan, or none to keep it on PostHog credits.

    The plan must match the run's harness, because `resolve_model_access` refuses a ChatGPT plan
    on a Claude run. `Task.create_run` then records the plan owner.
    """
    if runtime_adapter not in get_args(SubscriptionAdapter):
        return {}
    adapter = cast(SubscriptionAdapter, runtime_adapter)
    if not can_bill_plan_unattended(user, adapter):
        return {}
    return {f"{adapter}_model_access": "own-subscription"}
