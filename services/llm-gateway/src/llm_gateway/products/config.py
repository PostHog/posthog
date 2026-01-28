from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fastapi import HTTPException

from llm_gateway.config import get_settings


@dataclass(frozen=True)
class ProductConfig:
    allowed_application_ids: frozenset[str] | None = None  # None = all allowed
    allowed_models: frozenset[str] | None = None  # None = all allowed
    allow_api_keys: bool = True


# OAuth application IDs per region
TWIG_US_APP_ID = "019a3066-4aa2-0000-ca70-48ecdcc519cf"
TWIG_EU_APP_ID = "019a3067-5be7-0000-33c7-c6743eb59a79"
WIZARD_US_APP_ID = "019a0c79-b69d-0000-f31b-b41345208c9d"
WIZARD_EU_APP_ID = "019a12d0-6edd-0000-0458-86616af3a3db"

PRODUCTS: Final[dict[str, ProductConfig]] = {
    "llm_gateway": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "twig": ProductConfig(
        allowed_application_ids=frozenset({TWIG_US_APP_ID, TWIG_EU_APP_ID}),
        allowed_models=frozenset(
            {
                "claude-opus-4-5",
                "claude-sonnet-4-5",
                "claude-haiku-4-5",
                "gpt-5.2",
                "gpt-5-mini",
            }
        ),
        allow_api_keys=False,
    ),
    "wizard": ProductConfig(
        allowed_application_ids=frozenset({WIZARD_US_APP_ID, WIZARD_EU_APP_ID}),
        allowed_models=None,
        allow_api_keys=True,
    ),
    "django": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
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
}


ALLOWED_PRODUCTS: Final[frozenset[str]] = frozenset(PRODUCTS.keys())

PRODUCT_ALIASES: Final[dict[str, str]] = {
    "array": "twig",
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


def check_product_access(
    product: str,
    auth_method: str,
    application_id: str | None,
    model: str | None,
) -> tuple[bool, str | None]:
    """
    Check if request is authorized for product.
    Returns (allowed, error_message).
    """
    config = get_product_config(product)
    if config is None:
        return False, f"Unknown product: {product}"

    is_api_key = auth_method == "personal_api_key"
    if is_api_key and not config.allow_api_keys:
        return False, f"Product '{product}' requires OAuth authentication"

    is_oauth = auth_method == "oauth_access_token"
    if is_oauth and config.allowed_application_ids is not None:
        # Skip application ID checks in debug mode
        if not get_settings().debug and application_id not in config.allowed_application_ids:
            return False, f"OAuth application not authorized for product '{product}'"

    if model and config.allowed_models is not None:
        model_lower = model.lower()
        if not any(model_lower.startswith(allowed) for allowed in config.allowed_models):
            return False, f"Model '{model}' not allowed for product '{product}'"

    return True, None
