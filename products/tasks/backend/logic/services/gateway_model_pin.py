"""Gateway token model pins, free of Temporal worker imports so API code can use them."""

from typing import Any

from products.tasks.backend.model_catalog import MODELS, normalize_model_id

# Run-state stamp naming the product whose model-pinned token the sandbox holds.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"

# The agent SDK calls these on its own: haiku as its small fast model, and the sonnet the explore
# subagent's bare `sonnet` alias resolves to. The catalog does not offer them for selection.
SDK_IMPLICIT_MODELS: tuple[str, ...] = ("claude-haiku-4-5", "claude-sonnet-4-5")

_GATEWAY_RESTRICTED_MODEL_PRODUCTS: dict[str, frozenset[str]] = {
    "deepseek-ai/deepseek-v4-flash-0731": frozenset({"posthog_code", "review_hog"}),
    "deepseek-ai/deepseek-v4.1-flash-1017-fast": frozenset({"posthog_code", "review_hog", "signals_scout"}),
    # Excluded from every first-party pin; posthog_code admits it through DESKTOP_AGENT_MODELS.
    "zai-org/glm-5.2": frozenset({"posthog_code"}),
    "zai-org/glm-5.3": frozenset({"posthog_code", "review_hog"}),
    "zai-org/glm-5.3-flash": frozenset({"posthog_code", "review_hog"}),
}


def _first_party_pin(product: str) -> list[str]:
    routed = (model.id for model in MODELS if not model.id.startswith("@cf/"))
    admitted = (
        model_id
        for model_id in routed
        if product in _GATEWAY_RESTRICTED_MODEL_PRODUCTS.get(model_id, frozenset({product}))
    )
    return list(dict.fromkeys([*SDK_IMPLICIT_MODELS, *admitted]))


# Ids the legacy gateway serves to PostHog Desktop that the catalog lacks; older app builds call them.
_DESKTOP_LEGACY_MODELS: tuple[str, ...] = ("gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5-mini")


def gateway_pin(models: list[str]) -> list[str]:
    return [model for model in models if not model.startswith("@cf/")]


# Every model a PostHog Desktop session or cloud run may call, slash ids included. Go picks the provider.
DESKTOP_AGENT_MODELS: list[str] = list(
    dict.fromkeys([*SDK_IMPLICIT_MODELS, *(model.id for model in MODELS), *_DESKTOP_LEGACY_MODELS])
)
# The Go gateway refuses a pin longer than this at mint.
MAX_GATEWAY_PIN_LENGTH = 32
assert len(gateway_pin(DESKTOP_AGENT_MODELS)) <= MAX_GATEWAY_PIN_LENGTH, (
    "the desktop model pin outgrew the gateway limit"
)

# The legacy gateway's free tier. GLM-5.2 is listed twice: older clients send `@cf/`, Go serves the bare id.
FREE_TIER_MODELS: list[str] = [
    "@cf/zai-org/glm-5.2",
    "zai-org/glm-5.2",
    "deepseek-ai/deepseek-v4-flash-0731",
    "moonshotai/kimi-k3",
    "zai-org/glm-5.3-flash",
]

# Stamped on a free-plan run in place of its product, so the model-change guard reads the narrower pin.
FREE_TIER_PIN_KEY = "posthog_code:free"

PRODUCT_ALLOWED_MODELS: dict[str, list[str]] = {
    "posthog_ai": _first_party_pin("posthog_ai"),
    "account_audit": _first_party_pin("account_audit"),
    "posthog_code": DESKTOP_AGENT_MODELS,
    FREE_TIER_PIN_KEY: FREE_TIER_MODELS,
    "review_hog": _first_party_pin("review_hog"),
    "slack_app": _first_party_pin("slack_app"),
    "workflows": _first_party_pin("workflows"),
}


def model_allowed_by_product_pin(product: str, model: str | None) -> bool:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model:
        return True
    return normalize_model_id(model) in {normalize_model_id(entry) for entry in pin}


def pinned_run_allows_model(state: dict[str, Any] | None, model: str | None) -> bool:
    product = (state or {}).get(GATEWAY_PRODUCT_STATE_KEY)
    return not isinstance(product, str) or model_allowed_by_product_pin(product, model)
