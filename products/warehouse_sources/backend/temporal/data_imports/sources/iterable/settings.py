from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class IterableEndpointConfig:
    name: str
    path: str
    data_key: str  # JSON key the result array is nested under in the response body
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Iterable's list endpoints return their full result set in a single response wrapped under a
# named array (e.g. `{"campaigns": [...]}`). None of them expose a server-side timestamp filter
# (`startDateTime`/`updatedAt[after]`/etc.) we can verify, so every endpoint is full refresh —
# an "incremental" sync would still have to read every row each run. The higher-volume
# event/user streams live behind Iterable's async Export API (jobId polling, 4 req/min limit)
# and are intentionally deferred until that behavior can be verified against live credentials.
ITERABLE_ENDPOINTS: dict[str, IterableEndpointConfig] = {
    "campaigns": IterableEndpointConfig(name="campaigns", path="/api/campaigns", data_key="campaigns"),
    "channels": IterableEndpointConfig(name="channels", path="/api/channels", data_key="channels"),
    "lists": IterableEndpointConfig(name="lists", path="/api/lists", data_key="lists"),
    "message_types": IterableEndpointConfig(name="message_types", path="/api/messageTypes", data_key="messageTypes"),
    "templates": IterableEndpointConfig(
        name="templates", path="/api/templates", data_key="templates", primary_key="templateId"
    ),
}

ENDPOINTS = tuple(ITERABLE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ITERABLE_ENDPOINTS.items()
}
