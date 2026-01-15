from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from llm_gateway.config import get_settings


@dataclass(frozen=True)
class ProductConfig:
    allowed_application_ids: frozenset[str] | None = None  # None = all allowed
    allowed_models: frozenset[str] | None = None  # None = all allowed
    allow_api_keys: bool = True


# OAuth application IDs per region
ARRAY_US_APP_ID = "019a3066-4aa2-0000-ca70-48ecdcc519cf"
ARRAY_EU_APP_ID = "019a3067-5be7-0000-33c7-c6743eb59a79"
WIZARD_US_APP_ID = "019a0c79-b69d-0000-f31b-b41345208c9d"
WIZARD_EU_APP_ID = "019a12d0-6edd-0000-0458-86616af3a3db"

PRODUCTS: Final[dict[str, ProductConfig]] = {
    "llm_gateway": ProductConfig(
        allowed_application_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "array": ProductConfig(
        allowed_application_ids=frozenset({ARRAY_US_APP_ID, ARRAY_EU_APP_ID}),
        allowed_models=None,
        allow_api_keys=False,
    ),
    "wizard": ProductConfig(
        allowed_application_ids=frozenset({WIZARD_US_APP_ID, WIZARD_EU_APP_ID}),
        allowed_models=None,
        allow_api_keys=True,
    ),
}


def get_product_config(product: str) -> ProductConfig | None:
    return PRODUCTS.get(product)


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
