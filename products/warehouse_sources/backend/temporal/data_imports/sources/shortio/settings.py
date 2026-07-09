from dataclasses import dataclass, field


@dataclass
class ShortioEndpointConfig:
    name: str
    path: str
    # Short.io domain IDs are globally unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Top-level Short.io list endpoints. Only `domains` is synced in this version: it lists directly
# without a parent id. Links and click statistics are per-domain (fan-out) and are intentionally
# left out of v1. All endpoints are full refresh only — the domain list exposes no server-side
# ordered timestamp filter, so there is no incremental cursor to advance.
SHORTIO_ENDPOINTS: dict[str, ShortioEndpointConfig] = {
    "domains": ShortioEndpointConfig(name="domains", path="/api/domains"),
}

ENDPOINTS = tuple(SHORTIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
