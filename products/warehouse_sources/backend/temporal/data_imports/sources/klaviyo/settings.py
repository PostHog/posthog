from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
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
    # Extra query params merged into every request, e.g. a fields[...] sparse fieldset.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Passed to SourceResponse. "desc" defers persisting the incremental watermark to successful job
    # end instead of after every batch.
    sort_mode: SortMode = "asc"
    # Safety overlap subtracted from the incremental watermark on every run, re-pulling a window of
    # rows that merge dedupes on the primary key. Composes additively with the per-schema
    # incremental_field_lookback_seconds the framework applies before the value reaches the source.
    incremental_lookback: Optional[timedelta] = None
    # Fan out over every synced list, following the per-list profiles endpoint to materialize the
    # otherwise-unqueryable many-to-many list<->profile membership as one row per member.
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
    # Klaviyo only exposes list membership through per-list endpoints (which can't be called from
    # HogQL), so the many-to-many can't be joined. This table fans out one paginated request per list
    # to produce a flat {list_id, profile_id, joined_group_at} join table; it's opt-in (off by
    # default) to avoid the extra API cost.
    #
    # Incremental sync filters on `joined_group_at` (updated on re-join, so re-joins are picked up),
    # but Klaviyo has no removal timestamp: profiles removed from a list only disappear on a full
    # refresh. sort_mode="desc" so a crashed run whose resume state expires can't advance the
    # watermark past lists it never fetched, and the 24h lookback re-pulls joins that landed in
    # already-fetched lists mid-run; merge dedupes both on the primary key. No partition_key: the
    # partitioned merge predicate includes partition equality, and a re-join moves the row's
    # joined_group_at to a new partition, which would leave the old row behind as a duplicate.
    "list_profiles": KlaviyoEndpointConfig(
        name="list_profiles",
        path="/lists/{list_id}/profiles",
        default_incremental_field="joined_group_at",
        page_size=100,
        sort="-joined_group_at",
        sort_mode="desc",
        extra_params={"fields[profile]": "joined_group_at"},
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "joined_group_at",
                "type": IncrementalFieldType.DateTime,
                "field": "joined_group_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["list_id", "profile_id"],
        should_sync_default=False,
        fan_out_over_lists=True,
    ),
}

ENDPOINTS = tuple(KLAVIYO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KLAVIYO_ENDPOINTS.items()
}
