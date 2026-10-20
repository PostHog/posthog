"""Whether the runs a user starts away from Desktop and the web composer bill to their own plan.

Desktop and the web composer send `{adapter}_model_access` with every run they create, so they
do not read this. A surface that starts runs with no client in the loop, such as the Slack app,
reads the stored choice and checks that the plan can run unattended.
"""

from typing import cast, get_args

from django.db import transaction

from posthog.models.integration.codex import STATUS_CONNECTED, CodexUserIntegration
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.user import User

from products.tasks.backend.feature_flags import own_subscription_cloud_enabled
from products.tasks.backend.logic.model_access import ModelAccessMode, SubscriptionAdapter
from products.tasks.backend.models import UserTasksConfig

OWN_SUBSCRIPTION: ModelAccessMode = "own-subscription"
POSTHOG_GATEWAY: ModelAccessMode = "posthog-gateway"


def get_preferred_model_access(team_id: int, user_id: int, adapter: SubscriptionAdapter) -> ModelAccessMode:
    team_id = resolve_effective_team_id(team_id)
    preferences = (
        UserTasksConfig.objects.for_team(team_id, canonical=True)
        .filter(user_id=user_id)
        .values_list("model_access_preferences", flat=True)
        .first()
    )
    return OWN_SUBSCRIPTION if (preferences or {}).get(adapter) == OWN_SUBSCRIPTION else POSTHOG_GATEWAY


def set_preferred_model_access(team_id: int, user_id: int, adapter: SubscriptionAdapter, mode: ModelAccessMode) -> None:
    team_id = resolve_effective_team_id(team_id)
    with transaction.atomic():
        # team_id repeated in the lookup kwargs: for_team() only filters reads, so creation
        # needs the value passed explicitly.
        config, _ = (
            UserTasksConfig.objects.for_team(team_id, canonical=True)
            .select_for_update()
            .get_or_create(team_id=team_id, user_id=user_id)
        )
        preferences = dict(config.model_access_preferences or {})
        preferences[adapter] = mode
        config.model_access_preferences = preferences
        config.save(update_fields=["model_access_preferences", "updated_at"])


def can_bill_plan_unattended(user: User, adapter: SubscriptionAdapter, *, organization_id: str) -> bool:
    """Whether a run can bill to this user's plan when the user is not at a client.

    A Claude plan cannot, because PostHog stores no Claude token: the owner's Desktop must answer
    the token request each time an agent session starts. A ChatGPT plan can, because PostHog
    holds the token and refreshes it for the sandbox.
    """
    if adapter != "codex":
        return False
    integration = CodexUserIntegration.for_user(user.id)
    if integration is None or integration.status != STATUS_CONNECTED:
        return False
    return own_subscription_cloud_enabled(adapter, distinct_id=user.distinct_id, organization_id=organization_id)


def unattended_model_access_state(
    *, team_id: int, user_id: int, organization_id: str, runtime_adapter: str | None
) -> dict[str, str]:
    """The run-state keys that put a new run on the user's plan, or none to keep it on PostHog credits.

    The plan must match the run's harness, because `resolve_model_access` refuses a ChatGPT plan
    on a Claude run. `Task.create_run` then records the acting user as the plan owner.
    """
    if runtime_adapter not in get_args(SubscriptionAdapter):
        return {}
    adapter = cast(SubscriptionAdapter, runtime_adapter)
    if get_preferred_model_access(team_id, user_id, adapter) != OWN_SUBSCRIPTION:
        return {}
    user = User.objects.filter(id=user_id, is_active=True).first()
    if user is None or not can_bill_plan_unattended(user, adapter, organization_id=organization_id):
        return {}
    return {f"{adapter}_model_access": OWN_SUBSCRIPTION}
