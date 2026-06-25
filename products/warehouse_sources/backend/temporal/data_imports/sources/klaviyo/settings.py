from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class KlaviyoEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str = "updated_at"
    partition_key: Optional[str] = (
        None  # Field to partition by (should be created_at style field for stable partitions)
    )
    base_filter: Optional[str] = None  # e.g., "equals(messages.channel,'email')"
    page_size: Optional[int] = None  # Override default page size (100)
    sort: Optional[str] = None  # Sort field for the endpoint
    default_lookback_days: Optional[int] = None  # Limit first sync to last N days instead of full history
    primary_keys: list[str] = field(default_factory=lambda: ["id"])  # Primary key columns for dedup
    should_sync_default: bool = True  # Whether the table is selected for sync by default in the UI
    # Fan out over every synced list, following /lists/{list_id}/relationships/profiles to materialize
    # the otherwise-unqueryable many-to-many list<->profile membership as {list_id, profile_id} rows.
    # When True, `path` is a template with a `{list_id}` placeholder.
    fan_out_over_lists: bool = False


KLAVIYO_ENDPOINTS: dict[str, KlaviyoEndpointConfig] = {
    "email_campaigns": KlaviyoEndpointConfig(
        name="email_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'email')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "sms_campaigns": KlaviyoEndpointConfig(
        name="sms_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'sms')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "events": KlaviyoEndpointConfig(
        name="events",
        path="/events",
        default_incremental_field="datetime",
        partition_key="datetime",
        default_lookback_days=365,
        incremental_fields=[
            {
                "label": "datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "flows": KlaviyoEndpointConfig(
        name="flows",
        path="/flows",
        default_incremental_field="updated",
        partition_key="created",
        page_size=50,  # Flows endpoint max is 50
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "lists": KlaviyoEndpointConfig(
        name="lists",
        path="/lists",
        default_incremental_field="updated",
        partition_key="created",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "metrics": KlaviyoEndpointConfig(
        name="metrics",
        path="/metrics",
        page_size=0,  # Metrics endpoint doesn't support pagination
        incremental_fields=[],
    ),
    "profiles": KlaviyoEndpointConfig(
        name="profiles",
        path="/profiles",
        default_incremental_field="updated",
        partition_key="created",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Klaviyo only exposes list membership as JSON:API relationship links on the profile/list
    # objects (API endpoints that can't be called from HogQL), so the many-to-many can't be joined.
    # This table follows those links to produce a flat {list_id, profile_id} join table. It fans out
    # one paginated request per list, so it's opt-in (off by default) to avoid the extra API cost.
    "list_profiles": KlaviyoEndpointConfig(
        name="list_profiles",
        path="/lists/{list_id}/relationships/profiles",
        incremental_fields=[],
        primary_keys=["list_id", "profile_id"],
        should_sync_default=False,
        fan_out_over_lists=True,
    ),
}

ENDPOINTS = tuple(KLAVIYO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KLAVIYO_ENDPOINTS.items()
}
