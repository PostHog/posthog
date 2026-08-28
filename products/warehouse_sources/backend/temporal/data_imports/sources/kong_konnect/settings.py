from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Konnect serves the analytics API from region-specific hosts; the region must match the org's geo
# or the token authenticates against the wrong control plane and returns no data.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://us.api.konghq.com/v2",
    "eu": "https://eu.api.konghq.com/v2",
    "au": "https://au.api.konghq.com/v2",
    "me": "https://me.api.konghq.com/v2",
    "in": "https://in.api.konghq.com/v2",
    "sg": "https://sg.api.konghq.com/v2",
}

DEFAULT_REGION = "us"

# `size` is hard-capped at 1000 per page by the API.
MAX_PAGE_SIZE = 1000

# Absolute time-window queries must fall within the org's data retention period (plan-gated). On the
# first sync / full refresh there is no watermark to start from, so we walk back this many days. Users
# on longer-retention plans can raise it; a value beyond retention is clamped by the API to what exists.
DEFAULT_INITIAL_LOOKBACK_DAYS = 30


@dataclass
class KongKonnectEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Stable per-record timestamp used both as the incremental cursor and the partition key. Kong
    # request logs are append-only, so this never changes once written.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["request_id"])
    should_sync_default: bool = True


KONG_KONNECT_ENDPOINTS: dict[str, KongKonnectEndpointConfig] = {
    # Detailed per-request records for every request proxied through the gateway. This is the primary
    # (and only currently documented) analytics stream: POST /v2/api-requests with a time-window query
    # body. Incremental sync advances an absolute `request_start` watermark and pages ascending.
    "api_requests": KongKonnectEndpointConfig(
        name="api_requests",
        path="/api-requests",
        partition_key="request_start",
        incremental_fields=[
            {
                "label": "request_start",
                "type": IncrementalFieldType.DateTime,
                "field": "request_start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(KONG_KONNECT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KONG_KONNECT_ENDPOINTS.items()
}
