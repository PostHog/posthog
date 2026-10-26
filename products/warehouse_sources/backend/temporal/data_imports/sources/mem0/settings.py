"""Mem0 API endpoint catalog.

Reference: https://docs.mem0.ai/api-reference

- ``memories``: POST /v3/memories/ — page-number pagination (``page`` / ``page_size``, max 200)
  with a ``{count, next, previous, results}`` envelope. The endpoint requires a JSON ``filters``
  body; the same filter DSL exposes server-side ``created_at`` / ``updated_at`` comparison
  operators (``gte`` etc.), which is what makes incremental sync genuinely server-side.
- ``entities``: GET /v1/entities/ — returns the full entity list in one response (no documented
  pagination or timestamp filters), so it's full refresh only.
- ``events``: GET /v1/events/ — ``{count, next, previous, results}`` envelope followed via the
  ``next`` URL. No documented timestamp filters, so full refresh only.
- ``memory_history``: GET /v1/memories/{memory_id}/history/ — a bare array per memory, fanned out
  over the memories listing. The child has no filters, so incremental syncs bound the fan-out by
  filtering the memories listing on ``updated_at`` instead.
- ``organizations``: GET /api/v1/orgs/organizations/ — a bare array, no pagination.
- ``projects``: GET /api/v1/orgs/organizations/{org_id}/projects/ — a bare array per organization,
  fanned out over the organizations listing.
"""

from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MEM0_BASE_URL = "https://api.mem0.ai"

# Mem0's memory API is served at v3 (``POST /v3/memories/`` — the version we already read from),
# while entities and operation events stay on the stable ``/v1/`` paths. UNVERSIONED_API_VERSION
# ("v1") is the framework placeholder that pre-versioning source rows carry; it resolves to the
# exact same wire as "v3" here (memories on ``/v3/``, entities and events on ``/v1/``), so nothing
# on the request branches on the version. Declaring "v3" as the default just labels new sources for
# the memory API they actually target.
MEM0_API_VERSION_V3 = "v3"
SUPPORTED_VERSIONS = (UNVERSIONED_API_VERSION, MEM0_API_VERSION_V3)
DEFAULT_VERSION = MEM0_API_VERSION_V3

MEMORIES_ENDPOINT = "memories"
ENTITIES_ENDPOINT = "entities"
EVENTS_ENDPOINT = "events"
MEMORY_HISTORY_ENDPOINT = "memory_history"
ORGANIZATIONS_ENDPOINT = "organizations"
PROJECTS_ENDPOINT = "projects"


def _datetime_incremental_fields(*names: str) -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
        for name in names
    ]


@dataclass
class Mem0EndpointConfig:
    name: str
    path: str
    method: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Partition on a stable creation timestamp only — never `updated_at`, which is rewritten
    # upstream and would shuffle rows across partitions on every sync.
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    page_size: int | None = None


MEM0_ENDPOINTS: dict[str, Mem0EndpointConfig] = {
    MEMORIES_ENDPOINT: Mem0EndpointConfig(
        name=MEMORIES_ENDPOINT,
        path="/v3/memories/",
        method="POST",
        partition_key="created_at",
        incremental_fields=_datetime_incremental_fields("updated_at", "created_at"),
        page_size=100,
    ),
    ENTITIES_ENDPOINT: Mem0EndpointConfig(
        name=ENTITIES_ENDPOINT,
        path="/v1/entities/",
        method="GET",
    ),
    # Operation events (adds, searches, etc). Opt-in: it's an audit/observability stream that can
    # be high volume relative to the memory store itself.
    EVENTS_ENDPOINT: Mem0EndpointConfig(
        name=EVENTS_ENDPOINT,
        path="/v1/events/",
        method="GET",
        partition_key="created_at",
        should_sync_default=False,
    ),
    # Opt-in: one request per memory, so it costs far more API calls than the memories table.
    MEMORY_HISTORY_ENDPOINT: Mem0EndpointConfig(
        name=MEMORY_HISTORY_ENDPOINT,
        path="/v1/memories/{memory_id}/history/",
        method="GET",
        partition_key="created_at",
        incremental_fields=_datetime_incremental_fields("created_at"),
        should_sync_default=False,
    ),
    ORGANIZATIONS_ENDPOINT: Mem0EndpointConfig(
        name=ORGANIZATIONS_ENDPOINT,
        path="/api/v1/orgs/organizations/",
        method="GET",
        primary_keys=["org_id"],
    ),
    PROJECTS_ENDPOINT: Mem0EndpointConfig(
        name=PROJECTS_ENDPOINT,
        path="/api/v1/orgs/organizations/{org_id}/projects/",
        method="GET",
        # Project rows carry no org id, so the fan-out adds it and the key includes it.
        primary_keys=["org_id", "project_id"],
    ),
}

ENDPOINTS = tuple(MEM0_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MEM0_ENDPOINTS.items()
}
