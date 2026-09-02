from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Magento caps nothing server-side, but /V1/products rows are wide (custom attributes, media
# gallery, tier prices) and large catalogs make big pages slow, so keep the page moderate.
DEFAULT_PAGE_SIZE = 200


@dataclass
class AdobeCommerceEndpointConfig:
    name: str
    # Path below the `/rest/<store_code>/V1` prefix.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Most Magento collections are `GET <path>?searchCriteria[...]` returning
    # {"items": [...], "search_criteria": {...}, "total_count": N}. A handful of reference
    # endpoints (store views, websites, countries) take no searchCriteria and return a bare array.
    uses_search_criteria: bool = True
    page_size: int = DEFAULT_PAGE_SIZE
    # Server-side timestamp column used for both the `gteq` filter and the ascending sort on
    # incremental runs. `None` means the entity carries no modification timestamp, so the table
    # is full refresh only.
    incremental_field_name: Optional[str] = None
    # Column the pages are sorted by on a full refresh, so page boundaries stay stable while rows
    # are inserted mid-sync. searchCriteria sorts and filters address the underlying table column,
    # which is not always the name the response uses (`/V1/products` returns `id` but sorts on
    # `entity_id`), so set this whenever the two differ. Defaults to the primary key.
    full_refresh_sort_field: Optional[str] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_field_name is None:
            return []
        return [incremental_field(self.incremental_field_name)]

    @property
    def sort_field(self) -> str:
        return self.full_refresh_sort_field or self.primary_keys[0]


# Magento 2 / Adobe Commerce REST collections. Every entry below is a documented list endpoint on
# a stock install; the sales, catalog, customer and quote entities all carry `created_at` and
# `updated_at` columns that the searchCriteria filter can compare server-side, which is what makes
# them incremental. Transactions and coupons only ever get a `created_at` (their rows are never
# rewritten), and the reference tables carry no timestamps at all.
ADOBE_COMMERCE_ENDPOINTS: dict[str, AdobeCommerceEndpointConfig] = {
    "orders": AdobeCommerceEndpointConfig(
        name="orders",
        path="/orders",
        primary_keys=["entity_id"],
        incremental_field_name="updated_at",
    ),
    "invoices": AdobeCommerceEndpointConfig(
        name="invoices",
        path="/invoices",
        primary_keys=["entity_id"],
        incremental_field_name="updated_at",
    ),
    "shipments": AdobeCommerceEndpointConfig(
        name="shipments",
        path="/shipments",
        primary_keys=["entity_id"],
        incremental_field_name="updated_at",
    ),
    "creditmemos": AdobeCommerceEndpointConfig(
        name="creditmemos",
        path="/creditmemos",
        primary_keys=["entity_id"],
        incremental_field_name="updated_at",
    ),
    # `sales_payment_transaction` rows are written once and never updated, so `created_at` is a
    # stable cursor.
    "transactions": AdobeCommerceEndpointConfig(
        name="transactions",
        path="/transactions",
        primary_keys=["transaction_id"],
        incremental_field_name="created_at",
    ),
    "products": AdobeCommerceEndpointConfig(
        name="products",
        path="/products",
        primary_keys=["id"],
        full_refresh_sort_field="entity_id",
        page_size=100,
        incremental_field_name="updated_at",
    ),
    "categories": AdobeCommerceEndpointConfig(
        name="categories",
        path="/categories/list",
        primary_keys=["id"],
        full_refresh_sort_field="entity_id",
        incremental_field_name="updated_at",
    ),
    "customers": AdobeCommerceEndpointConfig(
        name="customers",
        path="/customers/search",
        primary_keys=["id"],
        full_refresh_sort_field="entity_id",
        incremental_field_name="updated_at",
    ),
    "carts": AdobeCommerceEndpointConfig(
        name="carts",
        path="/carts/search",
        primary_keys=["id"],
        full_refresh_sort_field="entity_id",
        incremental_field_name="updated_at",
    ),
    # `salesrule_coupon` rows are created with the rule and not rewritten afterwards.
    "coupons": AdobeCommerceEndpointConfig(
        name="coupons",
        path="/coupons/search",
        primary_keys=["coupon_id"],
        incremental_field_name="created_at",
    ),
    "customer_groups": AdobeCommerceEndpointConfig(
        name="customer_groups",
        path="/customerGroups/search",
        primary_keys=["id"],
    ),
    "product_attributes": AdobeCommerceEndpointConfig(
        name="product_attributes",
        path="/products/attributes",
        primary_keys=["attribute_id"],
    ),
    "tax_classes": AdobeCommerceEndpointConfig(
        name="tax_classes",
        path="/taxClasses/search",
        primary_keys=["class_id"],
    ),
    "store_views": AdobeCommerceEndpointConfig(
        name="store_views",
        path="/store/storeViews",
        primary_keys=["id"],
        uses_search_criteria=False,
    ),
    "store_groups": AdobeCommerceEndpointConfig(
        name="store_groups",
        path="/store/storeGroups",
        primary_keys=["id"],
        uses_search_criteria=False,
    ),
    "websites": AdobeCommerceEndpointConfig(
        name="websites",
        path="/store/websites",
        primary_keys=["id"],
        uses_search_criteria=False,
    ),
    "countries": AdobeCommerceEndpointConfig(
        name="countries",
        path="/directory/countries",
        primary_keys=["id"],
        uses_search_criteria=False,
    ),
}

ENDPOINTS = tuple(ADOBE_COMMERCE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ADOBE_COMMERCE_ENDPOINTS.items() if config.incremental_fields
}

# Ordered probe list for source-create validation. Magento answers an unauthorized *resource* with
# the same 401 it uses for an invalid token, so a single probe against a resource the integration
# happens not to have would look identical to bad credentials. Trying the common read ACLs in turn
# and accepting the first 200 keeps a narrowly-scoped integration connectable.
VALIDATION_PROBE_ENDPOINTS = ("orders", "products", "customers", "store_views")
