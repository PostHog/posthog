from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class LinkrunnerEndpointConfig:
    name: str
    path: str
    # Key inside the response `data` object that holds the row list (e.g. "campaigns", "users").
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime column to partition by (never an `updated_at`-style field).
    partition_key: Optional[str] = None
    default_limit: int = 100
    # Server-side timestamp filter param, set only where the API genuinely filters rows by it.
    incremental_start_param: Optional[str] = None
    # Fan out one paginated request per campaign, substituting each campaign's `display_id`.
    fan_out_over_campaigns: bool = False
    # Reporting API is capped at 1 request/minute/key (429 + Retry-After: 60); pace accordingly.
    rate_limited_per_minute: bool = False
    should_sync_default: bool = True


_ATTRIBUTED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "attributed_at",
        "type": IncrementalFieldType.DateTime,
        "field": "attributed_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


LINKRUNNER_ENDPOINTS: dict[str, LinkrunnerEndpointConfig] = {
    # Campaign list. No server-side timestamp filter is exposed (only filter/channel/domain/link),
    # so this is full refresh. `display_id` is the campaign's unique identifier across the API.
    "campaigns": LinkrunnerEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_key="campaigns",
        primary_keys=["display_id"],
        partition_key="created_at",
        default_limit=1000,  # max page size — minimise page count for a full-refresh list
        incremental_fields=[],
    ),
    # Users attributed to a campaign. Requires a per-campaign `display_id`, so we fan out over the
    # campaign list. `start_timestamp` genuinely filters which users are returned (per the API docs),
    # so this endpoint supports incremental sync on `attributed_at`.
    "attributed_users": LinkrunnerEndpointConfig(
        name="attributed_users",
        path="/attributed-users",
        data_key="users",
        # No documented per-record id, so the natural key is (campaign, user, attribution time).
        # `campaign_display_id` keeps the key unique table-wide across the fan-out.
        primary_keys=["campaign_display_id", "user_id", "attributed_at"],
        partition_key="attributed_at",
        default_limit=1000,
        incremental_start_param="start_timestamp",
        fan_out_over_campaigns=True,
        incremental_fields=_ATTRIBUTED_AT_INCREMENTAL,
    ),
    # Campaign-level performance metrics (clicks, installs, spend, revenue, ROAS, ...). The `from`/`to`
    # params only window the metrics, they don't filter the row list, so this is full refresh. Rate
    # limited to 1 request/minute/key.
    "reporting_campaigns": LinkrunnerEndpointConfig(
        name="reporting_campaigns",
        path="/reporting/campaigns",
        data_key="campaigns",
        primary_keys=["display_id"],
        partition_key="created_at",
        default_limit=100,  # reporting caps `limit` at 100 (larger values 422)
        rate_limited_per_minute=True,
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(LINKRUNNER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINKRUNNER_ENDPOINTS.items()
}
