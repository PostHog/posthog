"""Gateway token model pins, free of Temporal worker imports so API code can use them."""

from typing import Any

from products.tasks.backend.model_catalog import normalize_model_id

# Run-state stamp naming the product whose model-pinned token the sandbox holds.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"

# Every model a run calls (harness, the agent SDK's implicit haiku and sonnet, registry arms); an off-pin
# call fails with no fallback. Slash-namespaced ids stay out: Go serves them only on OpenAI shapes.
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
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model:
        return True
    return normalize_model_id(model) in {normalize_model_id(entry) for entry in pin}


def pinned_run_allows_model(state: dict[str, Any] | None, model: str | None) -> bool:
    product = (state or {}).get(GATEWAY_PRODUCT_STATE_KEY)
    return not isinstance(product, str) or model_allowed_by_product_pin(product, model)
