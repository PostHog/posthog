from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["cursor", "none"]


@dataclass
class SparkPostEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. SparkPost wraps every list endpoint in
    # ``{"results": [...]}``.
    data_path: str = "results"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    pagination: PaginationStyle = "none"
    per_page: int = 10000
    # Stable, immutable datetime field used for partitioning (never ``updated``/``last_update_time``).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side timestamp filter param (e.g. ``from``). Only set when the API genuinely filters
    # server-side — leaving it ``None`` keeps the endpoint full-refresh only.
    timestamp_filter_param: Optional[str] = None
    # First-sync lookback window for endpoints with a server-side timestamp filter. SparkPost only
    # retains message events for 10 days, so a "full" backfill of events is bounded to that window.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True

    @property
    def supports_incremental(self) -> bool:
        return self.timestamp_filter_param is not None


def _timestamp_incremental_fields(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Endpoint catalog. SparkPost (now part of Bird) ships no dedicated Airbyte/Fivetran connector, so
# coverage is drawn from the public SparkPost API: the Events Search API plus the management list
# endpoints a user typically wants in the warehouse (suppression list, recipient lists, templates,
# sending domains, subaccounts, webhooks).
#
# Incremental vs full refresh: only the Events Search API exposes a genuine server-side timestamp
# filter (``from``/``to``), so only ``events`` is marked incremental. The management list endpoints
# have no server-side time filter, so they ship as full refresh and dedupe on their primary key.
SPARKPOST_ENDPOINTS: dict[str, SparkPostEndpointConfig] = {
    # --- Append-only, server-side timestamp filter (incremental) ---
    "events": SparkPostEndpointConfig(
        name="events",
        path="/api/v1/events/message",
        primary_keys=["event_id"],
        pagination="cursor",
        per_page=10000,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="from",
        default_lookback_days=10,
    ),
    # --- Full refresh ---
    "suppression_list": SparkPostEndpointConfig(
        name="suppression_list",
        path="/api/v1/suppression-list",
        # A recipient can be suppressed independently for transactional and non-transactional mail,
        # surfacing as two rows that share a ``recipient`` — so the type is part of the key.
        primary_keys=["recipient", "type"],
        pagination="cursor",
        per_page=10000,
        partition_key="created",
    ),
    "recipient_lists": SparkPostEndpointConfig(
        name="recipient_lists",
        path="/api/v1/recipient-lists",
        primary_keys=["id"],
        pagination="none",
    ),
    "templates": SparkPostEndpointConfig(
        name="templates",
        path="/api/v1/templates",
        primary_keys=["id"],
        pagination="none",
    ),
    "sending_domains": SparkPostEndpointConfig(
        name="sending_domains",
        path="/api/v1/sending-domains",
        primary_keys=["domain"],
        pagination="none",
    ),
    "subaccounts": SparkPostEndpointConfig(
        name="subaccounts",
        path="/api/v1/subaccounts",
        primary_keys=["id"],
        pagination="none",
    ),
    "webhooks": SparkPostEndpointConfig(
        name="webhooks",
        path="/api/v1/webhooks",
        primary_keys=["id"],
        pagination="none",
    ),
}

ENDPOINTS = tuple(SPARKPOST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SPARKPOST_ENDPOINTS.items()
}

# SparkPost retains message events for only 10 days, so the first sync of ``events`` can reach back
# at most that far.
LIMITED_RETENTION_ENDPOINTS = {"events"}
