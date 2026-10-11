from dataclasses import dataclass, field
from typing import Any, Literal, Optional

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


@dataclass(frozen=True)
class LogzIOEndpointConfig:
    name: str
    path: str
    # How rows are extracted from the upstream API:
    # - "scroll": POST /v1/scroll, an Elasticsearch scroll cursor over log documents.
    # - "list": a single GET returning a full array (small config/definition snapshots).
    # - "page": POST with body-driven page-number pagination.
    # - "offset": POST with body-driven `from`/`size` offset pagination (audit trail).
    transport: Literal["scroll", "list", "page", "offset"]
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
    # Static request body fields (sort order, filters) merged into every paginated request.
    request_body: dict[str, Any] = field(default_factory=dict)
    # Set when the API returns no row id: the single primary key column is then filled with a hash
    # of the row content.
    hash_primary_key: bool = False


# Only `search_logs` has a genuine server-side time filter: the Elasticsearch DSL `range` query on
# `@timestamp` IS the query, so a mapped `db_incremental_field_last_value` is honored by construction
# (an ignored range filter would break search entirely). The definition/config endpoints
# (alerts, notification_endpoints, drop_filters) return small full-array snapshots with no
# updated-since filter, so they ship full refresh only. `security_events` and `audit_trail` also take a
# server-side time range on their event timestamp, so they sync incrementally too.
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
    # The security endpoints need an API token from a Logz.io Cloud SIEM (security) account.
    "security_events": LogzIOEndpointConfig(
        name="security_events",
        path="/v2/security/rules/events/search",
        transport="page",
        method="POST",
        data_selector="results",
        primary_keys=["alertEventId"],
        # Unix seconds of when the rule triggered. Partitioning reads integer keys as Unix seconds.
        partition_key="eventDate",
        incremental_fields=[
            {
                "label": "eventDate",
                "type": IncrementalFieldType.DateTime,
                "field": "eventDate",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        request_body={
            "filter": {"includeMutedEvents": True},
            "sort": [{"field": "DATE", "descending": False}],
        },
        should_sync_default=False,
    ),
    "security_rules": LogzIOEndpointConfig(
        name="security_rules",
        path="/v2/security/rules/search",
        transport="page",
        method="POST",
        data_selector="results",
        partition_key="createdAt",
        request_body={"sort": {"sortByField": "createdAt", "descending": False}},
        should_sync_default=False,
    ),
    "audit_trail": LogzIOEndpointConfig(
        name="audit_trail",
        path="/v1/audit-trail",
        transport="offset",
        method="POST",
        data_selector="results",
        # Audit events carry no id, and `date` is documented as Unix milliseconds, so it can't be a
        # datetime partition key (integer keys are read as Unix seconds).
        primary_keys=["audit_event_id"],
        hash_primary_key=True,
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        request_body={"sortDescending": False, "includeFiltersData": False},
        should_sync_default=False,
    ),
    "users": LogzIOEndpointConfig(
        name="users",
        path="/v1/user-management",
        transport="list",
        method="GET",
    ),
}

ENDPOINTS = tuple(LOGZIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LOGZIO_ENDPOINTS.items()
}
