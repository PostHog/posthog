from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

PAGE_SIZE = 100

_UPDATED_CREATED_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedDate",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedDate",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "createdDate",
        "type": IncrementalFieldType.DateTime,
        "field": "createdDate",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class WixEndpointConfig:
    name: str
    path: str
    # Wix wraps the request criteria under "search" on its search endpoints and "query" on its
    # query endpoints, and the response carries the cursors under a matching key. A GET endpoint
    # takes its sort as dotted query params under this key, for example "sorting.fieldName".
    body_key: str
    data_key: str
    cursors_key: str
    # Sort field requested on every page so paging stays stable while rows are written.
    sort_field: str
    # Permission a site owner grants the API key for this endpoint, quoted back when Wix returns 403.
    permission: str
    primary_key: str = "id"
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    paging: Literal["cursor", "offset"] = "cursor"
    # A GET endpoint takes its paging and sort as query params, not a request body.
    http_method: Literal["POST", "GET"] = "POST"
    page_size: int = PAGE_SIZE
    # Top-level request fields sent next to the criteria on every page.
    extra_body: dict[str, Any] = field(default_factory=dict)
    # Set when each result wraps the record under one key; the record's fields become the row root,
    # and filter and sort fields take this key as a prefix.
    record_key: Optional[str] = None
    # Set when each page of this parent endpoint is fanned out to a batch lookup by parent ID.
    parent: Optional[str] = None


WIX_ENDPOINTS: dict[str, WixEndpointConfig] = {
    "orders": WixEndpointConfig(
        name="orders",
        path="/ecom/v1/orders/search",
        body_key="search",
        data_key="orders",
        cursors_key="metadata",
        sort_field="createdDate",
        permission="Read eCommerce Orders",
        partition_key="createdDate",
        incremental_fields=list(_UPDATED_CREATED_INCREMENTAL_FIELDS),
    ),
    "products": WixEndpointConfig(
        name="products",
        path="/stores/v3/products/search",
        body_key="search",
        data_key="products",
        cursors_key="pagingMetadata",
        sort_field="createdDate",
        permission="Read Stores - all read permissions",
        partition_key="createdDate",
    ),
    "contacts": WixEndpointConfig(
        name="contacts",
        path="/contacts/v4/contacts/query",
        body_key="query",
        data_key="contacts",
        cursors_key="pagingMetadata",
        sort_field="createdDate",
        permission="Read Contacts",
        partition_key="createdDate",
    ),
    "members": WixEndpointConfig(
        name="members",
        path="/members/v1/members/query",
        body_key="query",
        data_key="members",
        cursors_key="pagingMetadata",
        sort_field="createdDate",
        permission="Read Members",
        partition_key="createdDate",
    ),
    "blog_posts": WixEndpointConfig(
        name="blog_posts",
        path="/blog/v3/posts/query",
        body_key="query",
        data_key="posts",
        cursors_key="pagingMetadata",
        sort_field="firstPublishedDate",
        permission="Read Blog",
        partition_key="firstPublishedDate",
    ),
    "blog_categories": WixEndpointConfig(
        name="blog_categories",
        path="/blog/v3/categories/query",
        body_key="query",
        data_key="categories",
        cursors_key="pagingMetadata",
        # Blog categories only page by offset.
        paging="offset",
        sort_field="id",
        permission="Read Blog",
    ),
    "store_categories": WixEndpointConfig(
        name="store_categories",
        path="/categories/v1/categories/query",
        body_key="query",
        data_key="categories",
        cursors_key="pagingMetadata",
        extra_body={"treeReference": {"appNamespace": "@wix/stores"}, "returnNonVisibleCategories": True},
        sort_field="createdDate",
        permission="Read categories",
        partition_key="createdDate",
        incremental_fields=list(_UPDATED_CREATED_INCREMENTAL_FIELDS),
    ),
    "bookings": WixEndpointConfig(
        name="bookings",
        path="/_api/bookings-reader/v2/extended-bookings/query",
        body_key="query",
        data_key="extendedBookings",
        cursors_key="pagingMetadata",
        record_key="booking",
        sort_field="createdDate",
        permission="Read Bookings - Including Participants",
        partition_key="createdDate",
        incremental_fields=list(_UPDATED_CREATED_INCREMENTAL_FIELDS),
    ),
    "order_transactions": WixEndpointConfig(
        name="order_transactions",
        path="/ecom/v1/payments/list-by-ids",
        body_key="orderIds",
        data_key="orderTransactions",
        cursors_key="metadata",
        parent="orders",
        sort_field="createdDate",
        permission="Read eCommerce Orders",
        primary_key="orderId",
        partition_key="orderCreatedDate",
    ),
    "order_fulfillments": WixEndpointConfig(
        name="order_fulfillments",
        path="/ecom/v1/fulfillments/list-by-ids",
        body_key="orderIds",
        data_key="ordersWithFulfillments",
        cursors_key="metadata",
        parent="orders",
        sort_field="createdDate",
        permission="Read eCommerce Orders",
        primary_key="orderId",
        partition_key="orderCreatedDate",
    ),
    "inventory_items": WixEndpointConfig(
        name="inventory_items",
        path="/stores/v3/inventory-items/query",
        body_key="query",
        data_key="inventoryItems",
        cursors_key="pagingMetadata",
        sort_field="createdDate",
        permission="Read inventory in v3 catalog",
        partition_key="createdDate",
        incremental_fields=list(_UPDATED_CREATED_INCREMENTAL_FIELDS),
    ),
    "pricing_plans": WixEndpointConfig(
        name="pricing_plans",
        path="/pricing-plans/v3/plans/query",
        body_key="query",
        data_key="plans",
        cursors_key="pagingMetadata",
        sort_field="createdDate",
        permission="Read Pricing Plans",
        partition_key="createdDate",
        incremental_fields=list(_UPDATED_CREATED_INCREMENTAL_FIELDS),
    ),
    "pricing_plan_orders": WixEndpointConfig(
        name="pricing_plan_orders",
        path="/pricing-plans/v2/orders",
        body_key="sorting",
        data_key="orders",
        cursors_key="pagingMetadata",
        # The list has no date filter and pages by offset, at most 50 orders a page. It sorts only
        # on createdDate or endDate.
        http_method="GET",
        paging="offset",
        page_size=50,
        sort_field="createdDate",
        permission="Read Pricing Plans Orders",
        partition_key="createdDate",
    ),
}

ENDPOINTS = tuple(WIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WIX_ENDPOINTS.items() if config.incremental_fields
}
