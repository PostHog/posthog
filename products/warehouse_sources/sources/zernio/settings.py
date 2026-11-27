from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

PaginationStyle = Literal["single_page", "skip", "cursor", "page"]

# Zernio documents no maximum page size for broadcasts, sequences and workflows. A larger
# limit that the server clamps would make the skip offset jump over rows, so those keep the
# documented default of 50.
DEFAULT_SKIP_PAGE_SIZE = 50
PAGE_SIZE = 100

# The conversation change feed returns every conversation written at or after `updatedSince`.
# A full read sends the epoch, so every row comes from Zernio's store and carries `updatedAt`.
FEED_START = "1970-01-01T00:00:00Z"

_UPDATED_AT_FIELD: list[IncrementalField] = [
    {
        "label": "updatedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedAt",
        "field_type": IncrementalFieldType.DateTime,
    }
]


@frozen
class ZernioEndpointConfig:
    name: str
    path: str
    data_selector: str
    pagination: PaginationStyle
    primary_keys: list[str]
    page_size: int = PAGE_SIZE
    # JSON path of the total row count, for skip pagination.
    total_path: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    # Zernio's creation timestamps never change, so they are the only partition keys.
    partition_key: Optional[str] = None
    # The query parameter that filters on `updatedAt` for incremental syncs.
    updated_since_param: Optional[str] = None
    # Send `updatedSince` from FEED_START on a full read too.
    always_send_updated_since: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)


ZERNIO_ENDPOINTS: dict[str, ZernioEndpointConfig] = {
    "profiles": ZernioEndpointConfig(
        name="profiles",
        path="/profiles",
        data_selector="profiles",
        pagination="skip",
        primary_keys=["_id"],
        total_path="total",
        # Profiles over the plan limit still hold accounts and posts.
        params={"includeOverLimit": "true"},
        partition_key="createdAt",
    ),
    "accounts": ZernioEndpointConfig(
        name="accounts",
        path="/accounts",
        data_selector="accounts",
        pagination="cursor",
        primary_keys=["_id"],
        params={"includeOverLimit": "true"},
    ),
    "account_groups": ZernioEndpointConfig(
        name="account_groups",
        path="/account-groups",
        data_selector="groups",
        pagination="single_page",
        primary_keys=["_id"],
    ),
    "users": ZernioEndpointConfig(
        name="users",
        path="/users",
        data_selector="users",
        pagination="single_page",
        primary_keys=["_id"],
        partition_key="createdAt",
    ),
    "posts": ZernioEndpointConfig(
        name="posts",
        path="/posts",
        data_selector="posts",
        pagination="cursor",
        primary_keys=["_id"],
        # Zernio keys the cursor on (createdAt, _id), so a post edited during the walk is neither
        # skipped nor read twice. The rows are not in `updatedAt` order.
        params={"sortBy": "created-asc"},
        partition_key="createdAt",
        updated_since_param="updatedSince",
        incremental_fields=_UPDATED_AT_FIELD,
    ),
    "contacts": ZernioEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="contacts",
        pagination="skip",
        primary_keys=["id"],
        total_path="pagination.total",
        partition_key="createdAt",
    ),
    "broadcasts": ZernioEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        data_selector="broadcasts",
        pagination="skip",
        primary_keys=["id"],
        page_size=DEFAULT_SKIP_PAGE_SIZE,
        total_path="pagination.total",
        partition_key="createdAt",
    ),
    "sequences": ZernioEndpointConfig(
        name="sequences",
        path="/sequences",
        data_selector="sequences",
        pagination="skip",
        primary_keys=["id"],
        page_size=DEFAULT_SKIP_PAGE_SIZE,
        total_path="pagination.total",
        partition_key="createdAt",
    ),
    "workflows": ZernioEndpointConfig(
        name="workflows",
        path="/workflows",
        data_selector="workflows",
        pagination="skip",
        primary_keys=["id"],
        page_size=DEFAULT_SKIP_PAGE_SIZE,
        total_path="pagination.total",
        partition_key="createdAt",
    ),
    "inbox_conversations": ZernioEndpointConfig(
        name="inbox_conversations",
        path="/inbox/conversations",
        data_selector="data",
        pagination="cursor",
        primary_keys=["id"],
        updated_since_param="updatedSince",
        # Without `updatedSince` Zernio reads each platform live, which drops `updatedAt` and
        # skips accounts the platform throttles. The change feed reads Zernio's own store.
        always_send_updated_since=True,
        incremental_fields=_UPDATED_AT_FIELD,
    ),
    "ads": ZernioEndpointConfig(
        name="ads",
        path="/ads",
        data_selector="ads",
        pagination="page",
        primary_keys=["_id"],
        # `all` includes the ads made in each platform's own ads manager. The metrics on each ad
        # cover Zernio's default window, the last 90 days.
        params={"source": "all"},
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(ZERNIO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ZERNIO_ENDPOINTS.items()
}
