from dataclasses import dataclass, field


@dataclass
class SimpleCastEndpointConfig:
    name: str
    path: str
    # Simplecast resource IDs are globally unique UUIDs, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Simplecast top-level list endpoints. Only account-level lists that need no parent id are
# included; per-podcast resources (episodes, analytics, seasons) are fan-out endpoints and are
# intentionally excluded from v1. All are full-refresh only: Simplecast exposes no documented
# server-side timestamp/cursor filter, so there is no incremental cursor to advance safely.
SIMPLECAST_ENDPOINTS: dict[str, SimpleCastEndpointConfig] = {
    "podcasts": SimpleCastEndpointConfig(name="podcasts", path="/podcasts"),
}

ENDPOINTS = tuple(SIMPLECAST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
