from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Single base URL for every project — Metorial has no regional hosts; the API key is
# project-scoped, so the project is inferred from the key.
METORIAL_BASE_URL = "https://api.metorial.com"

# Metorial's paginator caps `limit` at 100 server-side.
PAGE_SIZE = 100

_CREATED_AT_INCREMENTAL: IncrementalField = {
    "label": "created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "created_at",
    "field_type": IncrementalFieldType.DateTime,
}

_UPDATED_AT_INCREMENTAL: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class MetorialEndpointConfig:
    name: str
    path: str
    # Fields with a genuine server-side `<field>[gt]` date-range filter on the list endpoint,
    # AND present on the response object (the pipeline computes the watermark from row values).
    # Empty list = full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Metorial ids are globally unique (type-prefixed, e.g. `ses_...`), so `id` is safe table-wide.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `created_at` never changes once a record exists, unlike `updated_at`, so partitions are stable.
    partition_key: str | None = "created_at"


# Warehouse-worthy Metorial streams: the MCP-session observability resources (sessions, their
# messages/errors/tool calls, provider runs) plus the provider catalog and deployments.
# `session_messages`, `session_errors`, and `tool_calls` objects expose no `updated_at` field, so
# they sync incrementally on `created_at` (append-only); `providers` has no date filters at all.
METORIAL_ENDPOINTS: dict[str, MetorialEndpointConfig] = {
    "sessions": MetorialEndpointConfig(
        name="sessions",
        path="/sessions",
        incremental_fields=[_UPDATED_AT_INCREMENTAL, _CREATED_AT_INCREMENTAL],
    ),
    "session_messages": MetorialEndpointConfig(
        name="session_messages",
        path="/session-messages",
        incremental_fields=[_CREATED_AT_INCREMENTAL],
    ),
    "session_errors": MetorialEndpointConfig(
        name="session_errors",
        path="/session-errors",
        incremental_fields=[_CREATED_AT_INCREMENTAL],
    ),
    "tool_calls": MetorialEndpointConfig(
        name="tool_calls",
        path="/tool-calls",
        incremental_fields=[_CREATED_AT_INCREMENTAL],
    ),
    "provider_runs": MetorialEndpointConfig(
        name="provider_runs",
        path="/provider-runs",
        incremental_fields=[_UPDATED_AT_INCREMENTAL, _CREATED_AT_INCREMENTAL],
    ),
    "provider_deployments": MetorialEndpointConfig(
        name="provider_deployments",
        path="/provider-deployments",
        incremental_fields=[_UPDATED_AT_INCREMENTAL, _CREATED_AT_INCREMENTAL],
    ),
    "providers": MetorialEndpointConfig(
        name="providers",
        path="/providers",
        # `GET /providers` accepts no `created_at`/`updated_at` filters, so full refresh only.
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(METORIAL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METORIAL_ENDPOINTS.items()
}
