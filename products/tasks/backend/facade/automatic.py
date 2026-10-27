from typing import Literal

from posthog.models import User

from products.tasks.backend.logic.services.ai_run_defaults import resolve_ai_run_defaults
from products.tasks.backend.logic.services.model_catalogue import runtime_adapter_for
from products.tasks.backend.logic.services.unattended_plan import unattended_model_access_state

Billing = Literal["credits", "subscription"]


def plan_billing_available(user: User, runtime_adapter: str | None) -> bool:
    return bool(unattended_model_access_state(user, runtime_adapter=runtime_adapter))


def unattended_run_settings(
    *, team_id: int, user: User, model: str = "", reasoning_effort: str = "", billing: Billing = "credits"
) -> dict[str, str]:
    selection = resolve_ai_run_defaults(team_id, user.id)
    chosen = model or selection.model
    adapter = runtime_adapter_for(model) if model else selection.runtime_adapter
    effort = reasoning_effort if model else selection.reasoning_effort
    if not chosen or not adapter:
        raise ValueError("Choose a model for this step, or set a default coding model for the project.")
    access = unattended_model_access_state(user, runtime_adapter=adapter) if billing == "subscription" else {}
    if billing == "subscription" and not access:
        raise ValueError("Connect a ChatGPT plan in PostHog Desktop, or bill this step to PostHog credits.")
    return {
        "runtime_adapter": adapter,
        "model": chosen,
        **({"reasoning_effort": effort} if effort else {}),
        **access,
    }
