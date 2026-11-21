"""Gateway token model pins, free of Temporal worker imports so API code can use them."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.gateway_models import GatewayModel, list_gateway_models
from products.tasks.backend.model_catalog import MODELS, normalize_model_id, runtime_adapter_for_model

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

# Run-state stamp naming the product whose model-pinned token the sandbox holds.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"
GATEWAY_FAMILY_MODELS_STATE_KEY = "ai_gateway_family_models"

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
    # Only ReviewHog's arm-set trial calls it.
    "gpt-6.1-terra": frozenset({"review_hog"}),
}


def _admits(product: str, model_id: str) -> bool:
    return product in _GATEWAY_RESTRICTED_MODEL_PRODUCTS.get(normalize_model_id(model_id), frozenset({product}))


def _first_party_pin(product: str) -> list[str]:
    routed = (model.id for model in MODELS if not model.id.startswith("@cf/"))
    return list(dict.fromkeys([*SDK_IMPLICIT_MODELS, *(model_id for model_id in routed if _admits(product, model_id))]))


# Ids the legacy gateway serves to PostHog Desktop that the catalog lacks; older app builds call them.
_DESKTOP_LEGACY_MODELS: tuple[str, ...] = ("gpt-5.4", "gpt-5.3-codex", "gpt-5-mini")


def gateway_pin(models: list[str]) -> list[str]:
    return [model for model in models if not model.startswith("@cf/")]


# Every model a PostHog Desktop session or cloud run may call, slash ids included, except the ones reserved for
# other products. Go picks the provider.
DESKTOP_AGENT_MODELS: list[str] = list(
    dict.fromkeys(
        [
            *SDK_IMPLICIT_MODELS,
            *(model.id for model in MODELS if _admits("posthog_code", model.id)),
            *_DESKTOP_LEGACY_MODELS,
        ]
    )
)
# The Go gateway refuses a pin longer than this at mint.
MAX_GATEWAY_PIN_LENGTH = 64
assert len(gateway_pin(DESKTOP_AGENT_MODELS)) <= MAX_GATEWAY_PIN_LENGTH, (
    "the desktop model pin outgrew the gateway limit"
)

# The legacy gateway's free tier. GLM-5.2 is listed twice: older clients send `@cf/`, Go serves the bare id.
FREE_TIER_MODELS: list[str] = [
    "@cf/zai-org/glm-5.2",
    "zai-org/glm-5.2",
    "deepseek-ai/deepseek-v4-flash-0731",
    "moonshotai/kimi-k3",
    "moonshotai/kimi-k3.1-pro",
    "zai-org/glm-5.3-flash",
]

# Stamped on a free-plan run in place of its product, so the model-change guard reads the narrower pin.
FREE_TIER_PIN_KEY = "posthog_code:free"

PRODUCT_ALLOWED_MODELS: dict[str, list[str]] = {
    "posthog_ai": _first_party_pin("posthog_ai"),
    "account_audit": _first_party_pin("account_audit"),
    "onboarding": ["claude-sonnet-5", "claude-opus-4-8"],
    "conversations": ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5"],
    "background_agents": _first_party_pin("background_agents"),
    "posthog_code": DESKTOP_AGENT_MODELS,
    FREE_TIER_PIN_KEY: FREE_TIER_MODELS,
    "review_hog": _first_party_pin("review_hog"),
    "slack_app": _first_party_pin("slack_app"),
    "workflows": _first_party_pin("workflows"),
}


_AGENT_MODEL_FAMILIES: frozenset[str] = frozenset(
    {"claude-fable", "claude-opus", "claude-sonnet", "gpt-astra", "gpt-luna", "gpt-sol"}
)

PRODUCT_MODEL_FAMILIES: dict[str, frozenset[str]] = {
    "posthog_ai": _AGENT_MODEL_FAMILIES,
    "account_audit": _AGENT_MODEL_FAMILIES,
    "background_agents": _AGENT_MODEL_FAMILIES,
    "posthog_code": _AGENT_MODEL_FAMILIES,
    "review_hog": _AGENT_MODEL_FAMILIES,
    "slack_app": _AGENT_MODEL_FAMILIES,
    "workflows": _AGENT_MODEL_FAMILIES,
}

OFFERED_VERSIONS_PER_FAMILY = 2

_LISTING_PRODUCT: "Product" = "posthog_code"


@frozen
class FamilyModels:
    admitted: tuple[str, ...] = ()
    offered: frozenset[str] = frozenset()


def _newest_first(versions: Iterable[tuple[str, GatewayModel]]) -> list[str]:
    return [model_id for model_id, _ in sorted(versions, key=lambda version: version[1].release_date, reverse=True)]


def family_models(product: str, listing: Iterable[GatewayModel]) -> FamilyModels:
    families = PRODUCT_MODEL_FAMILIES.get(product)
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if not families or pin is None:
        return FamilyModels()

    pinned = {normalize_model_id(entry) for entry in pin}
    by_family: dict[str, dict[str, GatewayModel]] = {}
    for listed in listing:
        if listed.family in families:
            by_family.setdefault(listed.family, {}).setdefault(normalize_model_id(listed.id), listed)

    admitted: dict[str, GatewayModel] = {}
    current: set[str] = set()
    for versions in by_family.values():
        dated = all(listed.release_date for listed in versions.values())
        current.update(_newest_first(versions.items())[:OFFERED_VERSIONS_PER_FAMILY] if dated else versions)
        admitted.update(
            (model_id, listed)
            for model_id, listed in versions.items()
            if model_id not in pinned and runtime_adapter_for_model(model_id) is None and _admits(product, model_id)
        )

    room = max(MAX_GATEWAY_PIN_LENGTH - len(gateway_pin(pin)), 0)
    kept = tuple(_newest_first(admitted.items())[:room])
    return FamilyModels(admitted=kept, offered=frozenset(kept) & current)


def admitted_family_models(product: str) -> tuple[str, ...]:
    if product not in PRODUCT_MODEL_FAMILIES:
        return ()
    return family_models(product, list_gateway_models(_LISTING_PRODUCT)).admitted


def product_pin(product: str) -> list[str] | None:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None:
        return None
    return [*pin, *admitted_family_models(product)]


def offered_listing(product: str, listing: tuple[GatewayModel, ...]) -> tuple[GatewayModel, ...]:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None:
        return listing
    pinned = {normalize_model_id(entry) for entry in pin}
    offered = family_models(product, listing).offered
    seen: set[str] = set()
    rows: list[GatewayModel] = []
    for listed in listing:
        model_id = normalize_model_id(listed.id)
        if model_id in pinned or (model_id in offered and model_id not in seen):
            rows.append(listed)
        seen.add(model_id)
    return tuple(rows)


def _in_static_pin(pin: list[str], model: str) -> bool:
    return normalize_model_id(model) in {normalize_model_id(entry) for entry in pin}


def model_allowed_by_product_pin(product: str, model: str | None) -> bool:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model or _in_static_pin(pin, model):
        return True
    normalized = normalize_model_id(model)
    if runtime_adapter_for_model(normalized) is not None:
        return False
    return normalized in admitted_family_models(product)


def pinned_run_allows_model(state: dict[str, Any] | None, model: str | None) -> bool:
    product = (state or {}).get(GATEWAY_PRODUCT_STATE_KEY)
    if not isinstance(product, str):
        return True
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model or _in_static_pin(pin, model):
        return True
    minted = (state or {}).get(GATEWAY_FAMILY_MODELS_STATE_KEY)
    return isinstance(minted, list) and normalize_model_id(model) in minted
