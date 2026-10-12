from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_ORDER_INCREMENTAL_FIELDS: list[IncrementalField] = [
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
    # query endpoints, and the response carries the cursors under a matching key.
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
        incremental_fields=list(_ORDER_INCREMENTAL_FIELDS),
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
}

ENDPOINTS = tuple(WIX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WIX_ENDPOINTS.items() if config.incremental_fields
}
