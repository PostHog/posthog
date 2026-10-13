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
    "shopping_lists": CommercetoolsEndpointConfig(
        name="shopping_lists",
        path="/shopping-lists",
        scope="view_shopping_lists",
    ),
    "product_projections": CommercetoolsEndpointConfig(
        name="product_projections",
        path="/product-projections",
        scope="view_products",
    ),
    "product_types": CommercetoolsEndpointConfig(
        name="product_types",
        path="/product-types",
        scope="view_product_types",
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
    "standalone_prices": CommercetoolsEndpointConfig(
        name="standalone_prices",
        path="/standalone-prices",
        scope="view_standalone_prices",
    ),
    "stores": CommercetoolsEndpointConfig(
        name="stores",
        path="/stores",
        scope="view_stores",
    ),
    "channels": CommercetoolsEndpointConfig(
        name="channels",
        path="/channels",
        scope="view_channels",
    ),
    "customer_groups": CommercetoolsEndpointConfig(
        name="customer_groups",
        path="/customer-groups",
        scope="view_customer_groups",
    ),
    "states": CommercetoolsEndpointConfig(
        name="states",
        path="/states",
        scope="view_states",
    ),
    # Rows only exist once the Messages Query feature is switched on for the
    # project; before that commercetools persists no messages and the table syncs empty.
    # commercetools also deletes messages past the project's retention period, so this
    # table can only ever cover that window.
    "messages": CommercetoolsEndpointConfig(
        name="messages",
        path="/messages",
        scope="view_messages",
    ),
}

ENDPOINTS = tuple(COMMERCETOOLS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COMMERCETOOLS_ENDPOINTS.items() if config.incremental_fields
}
