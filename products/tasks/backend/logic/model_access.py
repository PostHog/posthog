from collections.abc import Mapping
from typing import Literal

from posthog.dataclasses import frozen

ModelAccessMode = Literal["posthog-gateway", "own-subscription"]
SubscriptionAdapter = Literal["claude", "codex"]


@frozen
class ModelAccess:
    """Who pays for a run's model use: PostHog, or the owner's plan for one adapter."""

    adapter: SubscriptionAdapter | None = None
    owner_id: int | None = None

    @property
    def kind(self) -> ModelAccessMode:
        return "posthog-gateway" if self.adapter is None else "own-subscription"

    def access_for(self, adapter: SubscriptionAdapter) -> ModelAccessMode:
        return "own-subscription" if adapter == self.adapter else "posthog-gateway"


class InvalidModelAccess(ValueError):
    pass


def resolve_model_access(state: Mapping[str, object]) -> ModelAccess:
    claude = state.get("claude_model_access") == "own-subscription"
    codex = state.get("codex_model_access") == "own-subscription"
    if claude and codex:
        raise InvalidModelAccess("Select only one subscription for this run.")
    if not claude and not codex:
        return ModelAccess()
    adapter: SubscriptionAdapter = "codex" if codex else "claude"
    if (state.get("runtime_adapter") or "claude") != adapter:
        raise InvalidModelAccess(f"The {adapter} subscription requires the {adapter} runtime.")
    owner = state.get(f"{adapter}_subscription_user_id")
    return ModelAccess(
        adapter=adapter,
        owner_id=owner if isinstance(owner, int) and not isinstance(owner, bool) else None,
    )
