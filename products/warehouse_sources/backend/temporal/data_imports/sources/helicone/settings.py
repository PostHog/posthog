from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Helicone runs regional deployments. An API key belongs to a single org in one region, so the
# host is chosen by the `region` form field rather than a user-supplied URL (no SSRF surface —
# the set is fixed).
HELICONE_HOSTS: dict[str, str] = {
    "us": "https://api.helicone.ai",
    "eu": "https://eu.api.helicone.ai",
}

REQUESTS_ENDPOINT = "requests"
SESSIONS_ENDPOINT = "sessions"
USERS_ENDPOINT = "users"
PROMPTS_ENDPOINT = "prompts"

# /v1/request/query-clickhouse is Helicone's bulk-export endpoint; their export CLI pages it with
# limit/offset up to 10k rows per request. Rows can embed full request/response bodies, so we keep
# pages an order of magnitude smaller to bound response sizes.
REQUESTS_PAGE_SIZE = 1000
SESSIONS_PAGE_SIZE = 1000
PROMPTS_PAGE_SIZE = 100

# Bound the first incremental sync of the request log to a recent window so an initial backfill of
# a high-volume org doesn't attempt to page through years of history. Subsequent incremental syncs
# only fetch rows newer than the stored cursor.
REQUESTS_DEFAULT_LOOKBACK_DAYS = 365


@dataclass
class HeliconeEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    supports_incremental: bool = False
    supports_append: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Must be a STABLE datetime field (never an update-tracking one) so partitions don't rewrite
    # on every sync.
    partition_key: str | None = None


HELICONE_ENDPOINTS: dict[str, HeliconeEndpointConfig] = {
    REQUESTS_ENDPOINT: HeliconeEndpointConfig(
        name=REQUESTS_ENDPOINT,
        path="/v1/request/query-clickhouse",
        primary_keys=["request_id"],
        supports_incremental=True,
        supports_append=True,
        # The request log is append-only, so the creation timestamp is a reliable server-side
        # cursor (the filter AST supports gte on request_created_at).
        incremental_fields=[
            {
                "label": "request_created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "request_created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="request_created_at",
    ),
    # Sessions, users, and prompts are aggregates/metadata whose rows change in place (a session
    # accrues requests, a user accrues cost) with no server-side "changed since" filter, so they
    # are full-refresh only.
    SESSIONS_ENDPOINT: HeliconeEndpointConfig(
        name=SESSIONS_ENDPOINT,
        path="/v1/session/query",
        primary_keys=["session_id"],
    ),
    USERS_ENDPOINT: HeliconeEndpointConfig(
        name=USERS_ENDPOINT,
        path="/v1/user/query",
        primary_keys=["user_id"],
    ),
    PROMPTS_ENDPOINT: HeliconeEndpointConfig(
        name=PROMPTS_ENDPOINT,
        path="/v1/prompt-2025/query",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(HELICONE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HELICONE_ENDPOINTS.items()
}
