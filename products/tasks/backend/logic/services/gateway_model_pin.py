"""Gateway token model pins, free of Temporal worker imports so API code can use them."""

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.gateway_models import GatewayModel, known_gateway_models, list_gateway_models
from products.tasks.backend.model_catalog import gateway_model_id, normalize_model_id

if TYPE_CHECKING:
    from posthog.llm.gateway_client import Product

# Run-state stamp naming the product whose model-pinned token the sandbox holds.
GATEWAY_PRODUCT_STATE_KEY = "ai_gateway_product"
GATEWAY_FAMILY_MODELS_STATE_KEY = "ai_gateway_family_models"

# The agent SDK calls these on its own: haiku as its small fast model, and the sonnet the explore
# subagent's bare `sonnet` alias resolves to.
SDK_IMPLICIT_MODELS: tuple[str, ...] = ("claude-haiku-4-5", "claude-sonnet-4-5")

_AGENT_MODEL_FAMILIES: frozenset[str] = frozenset(
    {
        "claude-fable",
        "claude-opus",
        "claude-sonnet",
        "gpt",
        "gpt-astra",
        "gpt-luna",
        "gpt-sol",
        "gpt-terra",
        "kimi-pro",
    }
)

# The gateway lists the DeepSeek models under no family, so each one stands as a family of its own.
_HOSTED_MODEL_FAMILIES: frozenset[str] = frozenset(
    {
        "glm",
        "glm-flash",
        "deepseek-ai/deepseek-v4-flash-0731",
        "deepseek-ai/deepseek-v4.1-flash-1017-fast",
    }
)

PRODUCT_MODEL_FAMILIES: dict[str, frozenset[str]] = {
    "posthog_ai": _AGENT_MODEL_FAMILIES,
    "account_audit": _AGENT_MODEL_FAMILIES,
    "background_agents": _AGENT_MODEL_FAMILIES,
    "posthog_code": _AGENT_MODEL_FAMILIES | _HOSTED_MODEL_FAMILIES,
    "review_hog": _AGENT_MODEL_FAMILIES | _HOSTED_MODEL_FAMILIES,
    "slack_app": _AGENT_MODEL_FAMILIES,
    "workflows": _AGENT_MODEL_FAMILIES,
}

_RESERVED_MODEL_PRODUCTS: dict[str, frozenset[str]] = {
    # Superseded by Kimi K3.1 Pro. Runs already pinned to it keep working.
    "moonshotai/kimi-k3": frozenset(PRODUCT_MODEL_FAMILIES),
    # The free tier and older PostHog Desktop builds call these.
    "zai-org/glm-5.2": frozenset({"posthog_code"}),
    "gpt-5.4": frozenset({"posthog_code"}),
    "gpt-5.3-codex": frozenset({"posthog_code"}),
    "gpt-5-mini": frozenset({"posthog_code"}),
    # Only ReviewHog's arm-set trial calls it.
    "gpt-6.1-terra": frozenset({"review_hog"}),
}

MODEL_FAMILY_ACCESS_FLAGS: dict[str, str] = {}

OFFERED_VERSIONS_PER_FAMILY = 2

# The Go gateway refuses a pin longer than this at mint.
MAX_GATEWAY_PIN_LENGTH = 64

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
    **{product: list(SDK_IMPLICIT_MODELS) for product in PRODUCT_MODEL_FAMILIES},
    "onboarding": ["claude-sonnet-5", "claude-opus-4-8"],
    "conversations": ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-sonnet-5"],
    FREE_TIER_PIN_KEY: FREE_TIER_MODELS,
}

_LISTING_PRODUCT: "Product" = "posthog_code"


def gateway_pin(models: list[str]) -> list[str]:
    return [model for model in models if not model.startswith("@cf/")]


@frozen
class FamilyModels:
    admitted: tuple[str, ...] = ()
    offered: frozenset[str] = frozenset()


def _family(listed: GatewayModel) -> str:
    return listed.family or normalize_model_id(listed.id)


def _admits(product: str, listed: GatewayModel) -> bool:
    reserved_for = _RESERVED_MODEL_PRODUCTS.get(normalize_model_id(listed.id))
    if reserved_for is not None:
        return product in reserved_for
    return _family(listed) in PRODUCT_MODEL_FAMILIES.get(product, frozenset())


def _newest_first(versions: Iterable[tuple[str, GatewayModel]]) -> list[str]:
    return [model_id for model_id, _ in sorted(versions, key=lambda version: version[1].release_date, reverse=True)]


def family_models(product: str, listing: Iterable[GatewayModel]) -> FamilyModels:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if product not in PRODUCT_MODEL_FAMILIES or pin is None:
        return FamilyModels()

    pinned = {normalize_model_id(entry) for entry in pin}
    by_family: dict[str, dict[str, GatewayModel]] = {}
    for listed in listing:
        by_family.setdefault(_family(listed), {}).setdefault(normalize_model_id(listed.id), listed)

    admitted: dict[str, GatewayModel] = {}
    current: set[str] = set()
    for versions in by_family.values():
        dated = all(listed.release_date for listed in versions.values())
        current.update(_newest_first(versions.items())[:OFFERED_VERSIONS_PER_FAMILY] if dated else versions)
        admitted.update(
            (model_id, listed)
            for model_id, listed in versions.items()
            if model_id not in pinned and _admits(product, listed)
        )

    room = max(MAX_GATEWAY_PIN_LENGTH - len(gateway_pin(pin)), 0)
    kept = tuple(_newest_first(admitted.items())[:room])
    offered = frozenset(
        model_id for model_id in kept if model_id in current and model_id not in _RESERVED_MODEL_PRODUCTS
    )
    return FamilyModels(admitted=kept, offered=offered)


def access_flag_for_model(model: str) -> str | None:
    if not MODEL_FAMILY_ACCESS_FLAGS:
        return None
    listed_id = gateway_model_id(model)
    listed = next((row for row in known_gateway_models(_LISTING_PRODUCT) if row.id == listed_id), None)
    return MODEL_FAMILY_ACCESS_FLAGS.get(_family(listed)) if listed else None


def agent_models(listing: Iterable[GatewayModel]) -> tuple[GatewayModel, ...]:
    return tuple(listed for listed in listing if any(_admits(product, listed) for product in PRODUCT_MODEL_FAMILIES))


def admitted_family_models(product: str) -> tuple[str, ...]:
    return family_models(product, known_gateway_models(_LISTING_PRODUCT)).admitted


def minted_family_models(product: str) -> tuple[str, ...]:
    return family_models(product, list_gateway_models(_LISTING_PRODUCT)).admitted


def product_pin(product: str) -> list[str] | None:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None:
        return None
    return [*pin, *minted_family_models(product)]


def _in_static_pin(pin: list[str], model: str) -> bool:
    return normalize_model_id(model) in {normalize_model_id(entry) for entry in pin}


def offered_listing(product: str, listing: tuple[GatewayModel, ...]) -> tuple[GatewayModel, ...]:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None:
        return listing
    if product not in PRODUCT_MODEL_FAMILIES:
        return tuple(listed for listed in listing if _in_static_pin(pin, listed.id))
    offered = family_models(product, listing).offered
    return tuple(listed for listed in listing if normalize_model_id(listed.id) in offered)


def admitted_listing(product: str, listing: tuple[GatewayModel, ...]) -> tuple[GatewayModel, ...]:
    admitted = set(family_models(product, listing).admitted)
    return tuple(listed for listed in listing if normalize_model_id(listed.id) in admitted)


def model_allowed_by_product_pin(product: str, model: str | None) -> bool:
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model or _in_static_pin(pin, model):
        return True
    return gateway_model_id(model) in admitted_family_models(product)


def pinned_run_allows_model(state: dict[str, Any] | None, model: str | None) -> bool:
    product = (state or {}).get(GATEWAY_PRODUCT_STATE_KEY)
    if not isinstance(product, str):
        return True
    pin = PRODUCT_ALLOWED_MODELS.get(product)
    if pin is None or not model or _in_static_pin(pin, model):
        return True
    minted = (state or {}).get(GATEWAY_FAMILY_MODELS_STATE_KEY)
    if not isinstance(minted, list):
        return gateway_model_id(model) in admitted_family_models(product)
    return gateway_model_id(model) in minted
