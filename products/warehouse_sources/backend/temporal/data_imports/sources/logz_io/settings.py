from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Logz.io hosts its API behind a region-specific domain matching the account's data region. The
# stored API token is only valid against the account's own region, so the region is a required
# source field. Codes verified to resolve as of implementation; `wa` (West US 2) is documented by
# Logz.io but was transiently unavailable when probed, so it's included on the documented value.
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://api.logz.io",
    "eu": "https://api-eu.logz.io",
    "uk": "https://api-uk.logz.io",
    "ca": "https://api-ca.logz.io",
    "au": "https://api-au.logz.io",
    "wa": "https://api-wa.logz.io",
}
DEFAULT_REGION = "us"


@dataclass
class LogzIOEndpointConfig:
    name: str
    path: str
    # How rows are extracted from the upstream API:
    # - "scroll": POST /v1/scroll, an Elasticsearch scroll cursor over log documents.
    # - "list": a single GET returning a full array (small config/definition snapshots).
    # - "page": POST with body-driven page-number pagination.
    transport: Literal["scroll", "list", "page"]
    method: Literal["GET", "POST"] = "GET"
    # Dotted path to the array of rows in the JSON response (e.g. "results"). Empty means the
    # response body is itself the array.
    data_selector: str = ""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Field to partition the warehouse table by. Must be a STABLE creation/event timestamp, never an
    # updated_at-style field that would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# Only `search_logs` has a genuine server-side time filter: the Elasticsearch DSL `range` query on
# `@timestamp` IS the query, so a mapped `db_incremental_field_last_value` is honored by construction
# (an ignored range filter would break search entirely). The definition/config endpoints
# (alerts, notification_endpoints, drop_filters) return small full-array snapshots with no
# updated-since filter, so they ship full refresh only.
LOGZIO_ENDPOINTS: dict[str, LogzIOEndpointConfig] = {
    "search_logs": LogzIOEndpointConfig(
        name="search_logs",
        path="/v1/scroll",
        transport="scroll",
        method="POST",
        # Elasticsearch document id, globally unique across the account's indices. Even if an
        # incremental window over-fetches at its boundary, merge dedupes on `_id`.
        primary_keys=["_id"],
        # `@timestamp` is the immutable log event time. Identifier normalization renders it as the
        # `atimestamp` column in the warehouse.
        partition_key="@timestamp",
        incremental_fields=[
            {
                "label": "@timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "@timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "alerts": LogzIOEndpointConfig(
        name="alerts",
        path="/v2/alerts",
        transport="list",
        method="GET",
        partition_key="createdAt",
    ),
    "triggered_alerts": LogzIOEndpointConfig(
        name="triggered_alerts",
        path="/v1/alerts/triggered-alerts",
        transport="page",
        method="POST",
        data_selector="results",
        primary_keys=["alertEventId"],
        partition_key="date",
        should_sync_default=False,
    ),
    "notification_endpoints": LogzIOEndpointConfig(
        name="notification_endpoints",
        path="/v1/endpoints",
        transport="list",
        method="GET",
    ),
    "drop_filters": LogzIOEndpointConfig(
        name="drop_filters",
        path="/v1/drop-filters/search",
        transport="page",
        method="POST",
        data_selector="results",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(LOGZIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LOGZIO_ENDPOINTS.items()
}
