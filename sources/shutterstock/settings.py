from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ShutterstockEndpointConfig:
    name: str
    # Path under https://api.shutterstock.com.
    path: str
    incremental_fields: list[IncrementalField]
    # Page size for page-number paginated endpoints; None = single unpaginated response.
    page_size: Optional[int] = None
    # Stable datetime field used for datetime partitioning. Only set where the field is
    # present on every row (never a mutable `updated_*` field — those rewrite partitions).
    partition_key: Optional[str] = None
    # Cursor field the API's `start_date` server-side filter narrows on. When set, the
    # request also passes `sort=oldest` so rows arrive in ascending cursor order and the
    # incremental watermark advances correctly.
    cursor_field: Optional[str] = None
    # True only where Shutterstock exposes a genuine server-side `start_date` filter.
    supports_incremental: bool = False
    # OAuth scope needed by this endpoint. Endpoints with a scope require an OAuth access
    # token; the consumer key/secret (HTTP Basic) auth method cannot reach them.
    required_scope: Optional[str] = None
    # For the `updated` feeds: with no `start_date` the API defaults to a 1-hour interval,
    # so the first sync bounds its window to this many days back instead.
    default_lookback_days: Optional[int] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Shutterstock v2 REST API (https://api-reference.shutterstock.com/).
#
# Catalog-wide search endpoints are deliberately excluded: they enumerate Shutterstock's
# whole media library, not the customer's account data. Incremental support is set only
# for resources that document a server-side `start_date` filter narrowing on a stable
# timestamp (`updated` feeds -> updated_time, license history -> download_time); those
# endpoints also accept `sort=oldest` for ascending cursor order. Everything else is
# full refresh.
SHUTTERSTOCK_ENDPOINTS: dict[str, ShutterstockEndpointConfig] = {
    "image_categories": ShutterstockEndpointConfig(
        name="image_categories",
        path="/v2/images/categories",
        incremental_fields=[],
    ),
    "video_categories": ShutterstockEndpointConfig(
        name="video_categories",
        path="/v2/videos/categories",
        incremental_fields=[],
    ),
    "images_updated": ShutterstockEndpointConfig(
        name="images_updated",
        path="/v2/images/updated",
        page_size=500,
        cursor_field="updated_time",
        supports_incremental=True,
        default_lookback_days=30,
        incremental_fields=[
            {
                "label": "updated_time",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "videos_updated": ShutterstockEndpointConfig(
        name="videos_updated",
        path="/v2/videos/updated",
        page_size=500,
        cursor_field="updated_time",
        supports_incremental=True,
        default_lookback_days=30,
        incremental_fields=[
            {
                "label": "updated_time",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "image_collections": ShutterstockEndpointConfig(
        name="image_collections",
        path="/v2/images/collections",
        page_size=100,
        required_scope="collections.view",
        incremental_fields=[],
    ),
    "video_collections": ShutterstockEndpointConfig(
        name="video_collections",
        path="/v2/videos/collections",
        page_size=100,
        required_scope="collections.view",
        incremental_fields=[],
    ),
    "image_licenses": ShutterstockEndpointConfig(
        name="image_licenses",
        path="/v2/images/licenses",
        page_size=200,
        partition_key="download_time",
        cursor_field="download_time",
        supports_incremental=True,
        required_scope="licenses.view",
        incremental_fields=[
            {
                "label": "download_time",
                "type": IncrementalFieldType.DateTime,
                "field": "download_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "video_licenses": ShutterstockEndpointConfig(
        name="video_licenses",
        path="/v2/videos/licenses",
        page_size=200,
        partition_key="download_time",
        cursor_field="download_time",
        supports_incremental=True,
        required_scope="licenses.view",
        incremental_fields=[
            {
                "label": "download_time",
                "type": IncrementalFieldType.DateTime,
                "field": "download_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "subscriptions": ShutterstockEndpointConfig(
        name="subscriptions",
        path="/v2/user/subscriptions",
        required_scope="purchases.view",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(SHUTTERSTOCK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHUTTERSTOCK_ENDPOINTS.items()
}
