from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Blueshift hosts one API per data region; the account's region is fixed at signup.
BLUESHIFT_REGION_URLS: dict[str, str] = {
    "us": "https://api.getblueshift.com",
    "eu": "https://api.eu.getblueshift.com",
}
DEFAULT_REGION = "us"

PAGE_SIZE = 100

# The v1 performance summary returns totals for a time window, so the stats table walks one UTC
# day at a time. The first sync reaches this far back when no watermark exists yet.
STATS_BACKFILL_DAYS = 365
# Opens, clicks and purchases keep arriving for days after a campaign sends, so every incremental
# stats sync reads this many days before its start position again.
STATS_REREAD_DAYS = 7

STATS_DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}


@frozen
class BlueshiftEndpointConfig:
    name: str
    path: str
    # JSON key wrapping the list, or None when the body is the list itself.
    data_selector: Optional[str]
    primary_keys: list[str]
    # "daily" reads one UTC day per request through the stats walk instead of the REST framework.
    pagination: Literal["page", "single", "daily"] = "page"
    incremental_fields: list[IncrementalField] | None = None
    partition_key: Optional[str] = None


BLUESHIFT_ENDPOINTS: dict[str, BlueshiftEndpointConfig] = {
    # Full refresh only: the list takes no sort param, and `created_after` would miss status
    # changes. Without `startdate` the list omits one-time campaigns older than 30 days, and the
    # documented meaning of that filter is not precise enough to send blindly.
    "campaigns": BlueshiftEndpointConfig(
        name="campaigns",
        path="/api/v2/campaigns.json",
        data_selector=None,
        primary_keys=["uuid"],
        partition_key="created_at",
    ),
    "campaign_stats": BlueshiftEndpointConfig(
        name="campaign_stats",
        path="/api/v1/campaigns.json",
        data_selector="campaigns",
        primary_keys=["uuid", "date"],
        pagination="daily",
        incremental_fields=[STATS_DATE_INCREMENTAL_FIELD],
        partition_key="date",
    ),
    "email_templates": BlueshiftEndpointConfig(
        name="email_templates",
        path="/api/v1/email_templates.json",
        data_selector="template",
        primary_keys=["uuid"],
    ),
    "push_templates": BlueshiftEndpointConfig(
        name="push_templates",
        path="/api/v1/push_templates.json",
        data_selector="template",
        primary_keys=["uuid"],
    ),
    "sms_templates": BlueshiftEndpointConfig(
        name="sms_templates",
        path="/api/v1/sms_templates.json",
        data_selector=None,
        primary_keys=["uuid"],
    ),
    "segments": BlueshiftEndpointConfig(
        name="segments",
        path="/api/v1/segments/list",
        data_selector="segments",
        primary_keys=["uuid"],
    ),
    "subscription_groups": BlueshiftEndpointConfig(
        name="subscription_groups",
        path="/api/v1/subscription_groups",
        data_selector="subscription_groups",
        primary_keys=["uuid"],
        pagination="single",
    ),
    "tags": BlueshiftEndpointConfig(
        name="tags",
        path="/api/v1/tag_contexts/list",
        data_selector=None,
        primary_keys=["id"],
        pagination="single",
    ),
}

ENDPOINTS = tuple(BLUESHIFT_ENDPOINTS.keys())

# Daily tables read their last days again on every sync, so append would store those days twice.
MERGE_ONLY_ENDPOINTS = tuple(name for name, config in BLUESHIFT_ENDPOINTS.items() if config.pagination == "daily")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in BLUESHIFT_ENDPOINTS.items() if config.incremental_fields
}
