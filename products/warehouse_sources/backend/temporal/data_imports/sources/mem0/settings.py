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
"""

from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MEM0_BASE_URL = "https://api.mem0.ai"

MEMORIES_ENDPOINT = "memories"
ENTITIES_ENDPOINT = "entities"
EVENTS_ENDPOINT = "events"

_DATETIME_INCREMENTAL_FIELD_NAMES = ("updated_at", "created_at")


def _datetime_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": name,
            "type": IncrementalFieldType.DateTime,
            "field": name,
            "field_type": IncrementalFieldType.DateTime,
        }
        for name in _DATETIME_INCREMENTAL_FIELD_NAMES
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
        incremental_fields=_datetime_incremental_fields(),
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
}

ENDPOINTS = tuple(MEM0_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MEM0_ENDPOINTS.items()
}
