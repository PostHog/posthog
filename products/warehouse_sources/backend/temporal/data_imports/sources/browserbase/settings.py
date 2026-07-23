from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class BrowserbaseEndpointConfig:
    name: str
    path: str
    # Field to partition Delta files by. Must be a stable creation-time timestamp so a row never
    # moves between partitions (Browserbase mutates `updatedAt`/`endedAt`, so those are unsafe).
    partition_key: str | None = None
    # Incremental cursor candidates. Left empty for every Browserbase endpoint: the list endpoints
    # expose no server-side timestamp filter (only `status`/`q` on sessions), so an "incremental"
    # sync would still fetch the whole collection each run. Full refresh is the honest strategy.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


BROWSERBASE_ENDPOINTS: dict[str, BrowserbaseEndpointConfig] = {
    "sessions": BrowserbaseEndpointConfig(
        name="sessions",
        path="/sessions",
        partition_key="createdAt",
        primary_keys=["id"],
    ),
    "projects": BrowserbaseEndpointConfig(
        name="projects",
        path="/projects",
        partition_key="createdAt",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(BROWSERBASE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BROWSERBASE_ENDPOINTS.items()
}
