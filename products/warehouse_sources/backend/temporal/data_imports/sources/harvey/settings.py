from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

HARVEY_BASE_URLS: dict[str, str] = {
    "us": "https://api.harvey.ai",
    "eu": "https://eu.api.harvey.ai",
    "au": "https://au.api.harvey.ai",
}

AUDIT_LOGS_PAGE_SIZE = 1000  # `take` max on GET /api/v1/logs/audit
# The history export APIs cap a single request at a 30-day range and recommend pulling one
# day at a time; responses are unpaginated, so smaller windows also bound response size.
HISTORY_WINDOW_SECONDS = 24 * 60 * 60
# Both the history export APIs and the audit log search endpoint only accept timestamps up
# to 1 year old. Stay a day under the limit so a request built "now" can't drift past it.
MAX_LOOKBACK_DAYS = 364
VAULT_PROJECTS_PAGE_SIZE = 100  # `per_page` max on GET /api/v1/vault/workspace/projects


@dataclass
class HarveyEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field used for partitioning (never an update-tracking field)
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


HARVEY_ENDPOINTS: dict[str, HarveyEndpointConfig] = {
    # Immutable workspace audit trail. Paginated forward in time by log ID
    # (GET /api/v1/logs/audit?from=<id>&take=1000); incremental syncs seed the cursor
    # server-side via GET /api/v1/logs/audit/search?time=<epoch>.
    "audit_logs": HarveyEndpointConfig(
        name="audit_logs",
        primary_keys=["id"],
        partition_key="timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Usage events (no prompt/response text). Windowed server-side via start_time/end_time.
    "usage_history": HarveyEndpointConfig(
        name="usage_history",
        primary_keys=["unique_usage_id"],
        partition_key="utc_time",
        incremental_fields=[
            {
                "label": "utc_time",
                "type": IncrementalFieldType.DateTime,
                "field": "utc_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Usage events including the full prompt/response text, feedback, and deep link.
    "query_history": HarveyEndpointConfig(
        name="query_history",
        primary_keys=["unique_usage_id"],
        partition_key="utc_time",
        incremental_fields=[
            {
                "label": "utc_time",
                "type": IncrementalFieldType.DateTime,
                "field": "utc_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Unpaginated full list with no server-side time filter - full refresh only.
    "client_matters": HarveyEndpointConfig(
        name="client_matters",
        primary_keys=["id"],
    ),
    # Page-number pagination. Rows are mutable (file counts, sharing, update timestamps),
    # so full refresh keeps the table current.
    "vault_projects": HarveyEndpointConfig(
        name="vault_projects",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(HARVEY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HARVEY_ENDPOINTS.items()
}
