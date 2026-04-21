from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException

from llm_gateway.bedrock import BEDROCK_MODEL_IDS, get_bedrock_model_access_candidates, get_bedrock_region_name
from llm_gateway.config import get_settings


@dataclass(frozen=True)
class ProductConfig:
    # Empty set (the default) or None means no OAuth application is authorized for this product.
    # To permit OAuth access, explicitly list the allowed application IDs.
    allowed_application_ids: frozenset[str] | None = frozenset()
    allowed_models: frozenset[str] | None = None  # None = all allowed
    allow_api_keys: bool = True


BEDROCK_MODELS = BEDROCK_MODEL_IDS

# OAuth application IDs per region
POSTHOG_CODE_US_APP_ID = "019a3066-4aa2-0000-ca70-48ecdcc519cf"
POSTHOG_CODE_EU_APP_ID = "019a3067-5be7-0000-33c7-c6743eb59a79"
TWIG_US_APP_ID = POSTHOG_CODE_US_APP_ID
TWIG_EU_APP_ID = POSTHOG_CODE_EU_APP_ID
WIZARD_US_APP_ID = "019a0c79-b69d-0000-f31b-b41345208c9d"
WIZARD_EU_APP_ID = "019a12d0-6edd-0000-0458-86616af3a3db"

PRODUCTS: Final[dict[str, ProductConfig]] = {
    "llm_gateway": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "posthog_code": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID}),
        allowed_models=frozenset(
            {
                "claude-opus-4-5",
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-sonnet-4-5",
                "claude-sonnet-4-6",
                "claude-haiku-4-5",
                "gpt-5.4",
                "gpt-5.3-codex",
                "gpt-5.2",
                "gpt-5-mini",
            }
            | BEDROCK_MODELS
        ),
        allow_api_keys=False,
    ),
    "background_agents": ProductConfig(
        allowed_application_ids=frozenset({POSTHOG_CODE_US_APP_ID, POSTHOG_CODE_EU_APP_ID}),
        allowed_models=frozenset(
            {
                "claude-opus-4-5",
                "claude-opus-4-6",
                "claude-opus-4-7",
                "claude-sonnet-4-5",
                "claude-haiku-4-5",
                "gpt-5.4",
                "gpt-5.3-codex",
                "gpt-5.2",
                "gpt-5-mini",
            }
            | BEDROCK_MODELS
        ),
        allow_api_keys=False,
    ),
    "wizard": ProductConfig(
        allowed_application_ids=frozenset({WIZARD_US_APP_ID, WIZARD_EU_APP_ID}),
        allowed_models=None,
        allow_api_keys=True,
    ),
    "llma_labeling": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5.4"}),
        allow_api_keys=True,
    ),
    "django": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "slack-posthog-code": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"claude-haiku-4-5"}),
        allow_api_keys=True,
    ),
    "growth": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "llma_translation": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "llma_summarization": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-nano", "gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
    "llma_eval_summary": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5-mini"}),
        allow_api_keys=True,
    ),
    "customer_archetype_classification": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-5-mini"}),
        allow_api_keys=True,
    ),
    "product_analytics": ProductConfig(
        allowed_application_ids=None,
        allowed_models=frozenset({"gpt-4.1-mini"}),
        allow_api_keys=True,
    ),
}


ALLOWED_PRODUCTS: Final[frozenset[str]] = frozenset(PRODUCTS.keys())

PRODUCT_ALIASES: Final[dict[str, str]] = {
    "array": "posthog_code",
    "twig": "posthog_code",
    "slack-twig": "slack-posthog-code",
}


def resolve_product_alias(product: str) -> str:
    return PRODUCT_ALIASES.get(product, product)


def get_product_config(product: str) -> ProductConfig | None:
    return PRODUCTS.get(resolve_product_alias(product))


def validate_product(product: str) -> str:
    resolved = resolve_product_alias(product)
    if resolved not in ALLOWED_PRODUCTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid product '{product}'. Allowed products: {', '.join(sorted(ALLOWED_PRODUCTS))}",
        )
    return resolved


def _model_matches_product_allowlist(
    model: str,
    allowed_models: frozenset[str],
    provider: str | None = None,
    settings: object | None = None,
) -> bool:
    model_candidates = {model.lower()}
    if provider == "bedrock":
        model_candidates = set(
            get_bedrock_model_access_candidates(model, region_name=get_bedrock_region_name(settings=settings))
        )

    allowed_prefixes = tuple(allowed_model.lower() for allowed_model in allowed_models)
    return any(
        model_candidate.startswith(allowed_prefix)
        for model_candidate in model_candidates
        for allowed_prefix in allowed_prefixes
    )


def check_product_access(
    product: str,
    auth_method: str,
    application_id: str | None,
    model: str | None,
    provider: str | None = None,
) -> tuple[bool, str | None]:
    """
    Check if request is authorized for product.
    Returns (allowed, error_message).
    """
    config = get_product_config(product)
    if config is None:
        return False, f"Unknown product: {product}"

    settings = get_settings()
    is_api_key = auth_method == "personal_api_key"
    if is_api_key and not config.allow_api_keys:
        return False, f"Product '{product}' requires OAuth authentication"

    is_oauth = auth_method == "oauth_access_token"
    if is_oauth and not settings.debug:
        # Skip application ID checks in debug mode
        allowed_application_ids = config.allowed_application_ids or frozenset()
        if application_id not in allowed_application_ids:
            return False, f"OAuth application not authorized for product '{product}'"

    if model and config.allowed_models is not None:
        if not _model_matches_product_allowlist(model, config.allowed_models, provider=provider, settings=settings):
            return False, f"Model '{model}' not allowed for product '{product}'"

    return True, None
