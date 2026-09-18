"""Gateway token model pins, free of Temporal worker imports so API code can use them."""

from typing import Any

from products.tasks.backend.model_catalog import MODELS, normalize_model_id

# Run-state stamp naming the product whose model-pinned token the sandbox holds.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"

# The agent SDK calls these on its own: haiku as its small fast model, and the sonnet the explore
# subagent's bare `sonnet` alias resolves to. The catalog does not offer them for selection.
SDK_IMPLICIT_MODELS: tuple[str, ...] = ("claude-haiku-4-5", "claude-sonnet-4-5")

# Every model a run calls; an off-pin call fails with no fallback. Slash-namespaced catalog ids stay out:
# Go serves them only on OpenAI shapes, so runs on them keep the Python gateway.
_FIRST_PARTY_AGENT_MODELS: list[str] = list(
    dict.fromkeys([*SDK_IMPLICIT_MODELS, *(model.id for model in MODELS if "/" not in model.id)])
)

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
