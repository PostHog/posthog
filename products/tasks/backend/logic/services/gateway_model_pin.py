"""Model pins carried on scoped gateway tokens, importable without the Temporal worker's modules."""

from typing import Any

from products.tasks.backend.model_catalog import normalize_model_id

# Stamped by the worker when a sandbox holds a model-pinned token, so a later model change keeps inside the pin.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"

# The harness models, the agent SDK's implicit haiku and sonnet calls, and every registry arm.
# Gateway-served (slash-namespaced) models stay out: the Go gateway serves them only on OpenAI
# shapes, and a pin entry can only deny, since the gateway drops ids it cannot resolve.
_FIRST_PARTY_AGENT_MODELS: list[str] = [
    "claude-haiku-4-5",
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-fable-5",
    "claude-fable-5-1",
    "gpt-5",
    "gpt-5.5",
    "gpt-5.6-sol",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
    "gpt-6-astra",
]

PRODUCT_ALLOWED_MODELS: dict[str, list[str]] = {
    "review_hog": _FIRST_PARTY_AGENT_MODELS,
    "slack_app": _FIRST_PARTY_AGENT_MODELS,
}


def model_allowed_by_product_pin(product: str, model: str | None) -> bool:
    """Whether a product's token pin admits the model; an unpinned product or unset model always does."""
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model:
        return True
    return normalize_model_id(model) in {normalize_model_id(entry) for entry in pin}


def pinned_run_allows_model(state: dict[str, Any] | None, model: str | None) -> bool:
    """Whether the model-pinned token stamped on a run's state admits the model."""
    product = (state or {}).get(GATEWAY_PRODUCT_STATE_KEY)
    return not isinstance(product, str) or model_allowed_by_product_pin(product, model)
