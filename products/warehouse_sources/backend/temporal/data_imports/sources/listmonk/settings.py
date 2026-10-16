from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

LISTMONK_API_PATH = "/api"

PAGE_SIZE = 500

# Campaign ids sent per analytics request, to keep the query string short.
ANALYTICS_BATCH_SIZE = 50
ANALYTICS_TYPES = ("views", "clicks", "bounces")
# The analytics endpoint needs a bounded range. Listmonk has no campaign data before its first release.
ANALYTICS_FROM_DATE = "2019-01-01"

UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}


@frozen
class ListmonkEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Listmonk accepts `order_by` only from a fixed list per resource. None sends no `order_by`.
    order_by: Optional[str] = "created_at"
    extra_params: Optional[dict[str, str]] = None
    incremental_fields: Optional[list[IncrementalField]] = None
    partition_key: Optional[str] = "created_at"


LISTMONK_ENDPOINTS: dict[str, ListmonkEndpointConfig] = {
    # The incremental filter is a SQL expression in `query`, which needs the API user to hold the
    # `subscribers:sql_query` permission. With no `order_by`, Listmonk sorts by `subscribers.id`,
    # which is unique and never changes. Paging by `updated_at` would let a row updated mid-walk,
    # or one of thousands imported with the same timestamp, slip past the offset.
    "subscribers": ListmonkEndpointConfig(
        name="subscribers",
        path="/subscribers",
        primary_keys=["id"],
        order_by=None,
        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
    ),
    "lists": ListmonkEndpointConfig(
        name="lists",
        path="/lists",
        primary_keys=["id"],
    ),
    "campaigns": ListmonkEndpointConfig(
        name="campaigns",
        path="/campaigns",
        primary_keys=["id"],
        extra_params={"no_body": "true"},
    ),
    "bounces": ListmonkEndpointConfig(
        name="bounces",
        path="/bounces",
        primary_keys=["id"],
    ),
    "campaign_analytics": ListmonkEndpointConfig(
        name="campaign_analytics",
        path="/campaigns/analytics/{type}",
        primary_keys=["campaign_id", "type", "timestamp"],
        order_by=None,
        partition_key=None,
    ),
}

ENDPOINTS = tuple(LISTMONK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in LISTMONK_ENDPOINTS.items() if config.incremental_fields
}
