from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every queryable commercetools resource supports `where` predicates and
# sorting on lastModifiedAt, so the incremental menu is shared.
_LAST_MODIFIED_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "lastModifiedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "lastModifiedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class CommercetoolsEndpointConfig:
    name: str
    path: str
    # OAuth scope the endpoint needs (surfaced in the source caption).
    scope: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_LAST_MODIFIED_INCREMENTAL_FIELDS))
    # Every commercetools resource carries an immutable createdAt.
    partition_key: str = "createdAt"


COMMERCETOOLS_ENDPOINTS: dict[str, CommercetoolsEndpointConfig] = {
    "orders": CommercetoolsEndpointConfig(
        name="orders",
        path="/orders",
        scope="view_orders",
    ),
    "customers": CommercetoolsEndpointConfig(
        name="customers",
        path="/customers",
        scope="view_customers",
    ),
    "payments": CommercetoolsEndpointConfig(
        name="payments",
        path="/payments",
        scope="view_payments",
    ),
    "carts": CommercetoolsEndpointConfig(
        name="carts",
        path="/carts",
        scope="view_orders",
    ),
    "product_projections": CommercetoolsEndpointConfig(
        name="product_projections",
        path="/product-projections",
        scope="view_products",
    ),
    "categories": CommercetoolsEndpointConfig(
        name="categories",
        path="/categories",
        scope="view_categories",
    ),
    "discount_codes": CommercetoolsEndpointConfig(
        name="discount_codes",
        path="/discount-codes",
        scope="view_discount_codes",
    ),
    "inventory": CommercetoolsEndpointConfig(
        name="inventory",
        path="/inventory",
        scope="view_products",
    ),
}

ENDPOINTS = tuple(COMMERCETOOLS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COMMERCETOOLS_ENDPOINTS.items() if config.incremental_fields
}
