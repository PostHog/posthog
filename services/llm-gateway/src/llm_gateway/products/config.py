from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ProductConfig:
    allowed_client_ids: frozenset[str] | None = None  # None = all allowed
    allowed_models: frozenset[str] | None = None  # None = all allowed
    allow_api_keys: bool = True


PRODUCTS: Final[dict[str, ProductConfig]] = {
    "llm_gateway": ProductConfig(
        allowed_client_ids=None,
        allowed_models=None,
        allow_api_keys=True,
    ),
    "array": ProductConfig(
        allowed_client_ids=frozenset(),  # No OAuth clients allowed yet
        allowed_models=frozenset({"claude-3-5-haiku", "gpt-4o-mini"}),
        allow_api_keys=False,
    ),
    "wizard": ProductConfig(
        allowed_client_ids=frozenset(),  # No OAuth clients allowed yet
        allowed_models=None,
        allow_api_keys=True,
    ),
}


def get_product_config(product: str) -> ProductConfig | None:
    return PRODUCTS.get(product)


def check_product_access(
    product: str,
    auth_method: str,
    client_id: str | None,
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
    if is_oauth and config.allowed_client_ids is not None:
        if client_id not in config.allowed_client_ids:
            return False, f"OAuth client not authorized for product '{product}'"

    if model and config.allowed_models is not None:
        if not any(allowed in model.lower() for allowed in config.allowed_models):
            return False, f"Model '{model}' not allowed for product '{product}'"

    return True, None
