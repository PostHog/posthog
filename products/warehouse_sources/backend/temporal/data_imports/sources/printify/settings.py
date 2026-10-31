from dataclasses import dataclass, field
from enum import StrEnum


class PrintifyFanOut(StrEnum):
    # One request per catalog blueprint.
    BLUEPRINT = "blueprint"
    # One request per (blueprint, print provider) pair used by a product in a connected shop. The full
    # catalog has thousands of pairs behind a 100 requests/minute limit, and these pairs are the ones
    # that resolve the variant ids on synced products and order line items.
    PRODUCT_CATALOG_PAIR = "product_catalog_pair"
    # One request per product in each connected shop.
    PRODUCT = "product"


@dataclass
class PrintifyEndpointConfig:
    name: str
    # Path relative to the API base URL; `{shop_id}` is filled per shop for shop-scoped endpoints.
    path: str
    # Most Printify resources (products, orders, webhooks) live under a shop, so the source lists
    # shops first and fans out per shop.
    shop_scoped: bool = False
    # Laravel-style page-number pagination (`?page=`, `current_page`/`last_page`/`next_page_url`).
    # Non-paginated endpoints return a bare JSON array in one response.
    paginated: bool = False
    # Value for the `limit` query param; None means the endpoint doesn't accept one.
    page_size: int | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fields stripped from rows before they're yielded (credentials that must not land in a
    # warehouse table).
    redact_fields: list[str] = field(default_factory=list)
    # Child endpoints request one path per parent object; the path holds the parent's id placeholders.
    fan_out: PrintifyFanOut | None = None
    query_params: dict[str, str] = field(default_factory=dict)


# Printify REST API v1 list endpoints (https://developers.printify.com). All are full-refresh only:
# no list endpoint documents a server-side `updated_at`/`since` filter, so there is no incremental
# cursor to advance. Shop-scoped endpoints use a composite primary key — object ids look globally
# unique (Mongo-style), but the docs don't guarantee it, so the shop id is included to be safe.
PRINTIFY_ENDPOINTS: dict[str, PrintifyEndpointConfig] = {
    "shops": PrintifyEndpointConfig(name="shops", path="/shops.json"),
    "products": PrintifyEndpointConfig(
        name="products",
        path="/shops/{shop_id}/products.json",
        shop_scoped=True,
        paginated=True,
        page_size=100,
        primary_keys=["shop_id", "id"],
    ),
    "orders": PrintifyEndpointConfig(
        name="orders",
        path="/shops/{shop_id}/orders.json",
        shop_scoped=True,
        paginated=True,
        # The orders endpoint caps results at 10 per page, so we rely on the API default.
        page_size=None,
        primary_keys=["shop_id", "id"],
    ),
    "uploads": PrintifyEndpointConfig(
        name="uploads",
        path="/uploads.json",
        paginated=True,
        page_size=100,
    ),
    "webhooks": PrintifyEndpointConfig(
        name="webhooks",
        path="/shops/{shop_id}/webhooks.json",
        shop_scoped=True,
        primary_keys=["shop_id", "id"],
        # A webhook's signing secret would let any table reader forge Printify webhook requests.
        redact_fields=["secret"],
    ),
    "blueprints": PrintifyEndpointConfig(name="blueprints", path="/catalog/blueprints.json"),
    "print_providers": PrintifyEndpointConfig(name="print_providers", path="/catalog/print_providers.json"),
    "blueprint_print_providers": PrintifyEndpointConfig(
        name="blueprint_print_providers",
        path="/catalog/blueprints/{blueprint_id}/print_providers.json",
        fan_out=PrintifyFanOut.BLUEPRINT,
        primary_keys=["blueprint_id", "id"],
    ),
    # Variant ids are shared by every print provider of a blueprint, so the key needs both parents.
    "catalog_variants": PrintifyEndpointConfig(
        name="catalog_variants",
        path="/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants.json",
        fan_out=PrintifyFanOut.PRODUCT_CATALOG_PAIR,
        # Without it the API omits out-of-stock variants, which products and orders still reference.
        query_params={"show-out-of-stock": "1"},
        primary_keys=["blueprint_id", "print_provider_id", "id"],
    ),
    # v1 shipping profiles, exploded to one row per variant and destination country.
    "catalog_shipping_rates": PrintifyEndpointConfig(
        name="catalog_shipping_rates",
        path="/catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/shipping.json",
        fan_out=PrintifyFanOut.PRODUCT_CATALOG_PAIR,
        primary_keys=["blueprint_id", "print_provider_id", "variant_id", "country"],
    ),
    "product_gpsr": PrintifyEndpointConfig(
        name="product_gpsr",
        path="/shops/{shop_id}/products/{product_id}/gpsr.json",
        shop_scoped=True,
        fan_out=PrintifyFanOut.PRODUCT,
        primary_keys=["shop_id", "product_id"],
    ),
}

ENDPOINTS = tuple(PRINTIFY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
