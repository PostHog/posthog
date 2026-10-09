from collections.abc import Mapping
from typing import Literal

from posthog.dataclasses import frozen

ModelAccessMode = Literal["posthog-gateway", "own-subscription"]
SubscriptionAdapter = Literal["claude", "codex"]
ClaudeSubscriptionSource = Literal["relay", "server"]
InferenceBilling = Literal["posthog", "own_subscription"]
# The credential a run needs for its model calls: the connected ChatGPT account, or the Claude
# subscription token that the server stores for the owner.
RunCredentialKind = Literal["claude_subscription", "codex"]

CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY = "claude_subscription_source"
# The run state keys that select who pays for model use. A server-side caller stamps them. The
# owner key `{adapter}_subscription_user_id` is not in this set, because run creation stamps it.
INFERENCE_STATE_KEYS: frozenset[str] = frozenset(
    {"claude_model_access", "codex_model_access", CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY}
)


@frozen
class ModelAccess:
    """Who pays for a run's model use: PostHog, or the owner's plan for one adapter."""

    adapter: SubscriptionAdapter | None = None
    owner_id: int | None = None
    # Where a Claude plan token comes from: the client that answers the run's credential request,
    # or the token that the server stores for the owner.
    claude_subscription_source: ClaudeSubscriptionSource = "relay"

    @property
    def kind(self) -> ModelAccessMode:
        return "posthog-gateway" if self.adapter is None else "own-subscription"

    def access_for(self, adapter: SubscriptionAdapter) -> ModelAccessMode:
        return "own-subscription" if adapter == self.adapter else "posthog-gateway"

    @property
    def billing(self) -> InferenceBilling:
        return "posthog" if self.adapter is None else "own_subscription"

    @property
    def credential_kind(self) -> RunCredentialKind | None:
        """The credential that the server must hold for the run. None for a gateway run and for a
        relayed Claude plan token, which the server never holds."""
        if self.adapter is None:
            return None
        if self.adapter == "codex":
            return "codex"
        return "claude_subscription" if self.claude_subscription_source == "server" else None

    @property
    def uses_stored_claude_subscription(self) -> bool:
        return self.credential_kind == "claude_subscription"


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
    server_source = adapter == "claude" and state.get(CLAUDE_SUBSCRIPTION_SOURCE_STATE_KEY) == "server"
    return ModelAccess(
        adapter=adapter,
        owner_id=owner if isinstance(owner, int) and not isinstance(owner, bool) else None,
        claude_subscription_source="server" if server_source else "relay",
    )


def inference_billing_for_state(state: Mapping[str, object]) -> InferenceBilling:
    """Who pays for the model use of a run with this state.

    Raises ``InvalidModelAccess`` for a state that no run can have, such as two subscriptions.
    """
    return resolve_model_access(state).billing
