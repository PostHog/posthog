from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class DripEndpointConfig:
    name: str
    path: str
    # Key wrapping the list in the JSON response, e.g. {"subscribers": [...]}.
    data_key: str
    primary_keys: list[str]
    # Page size to request. None means the endpoint is not paginated (returns the full list in one response).
    per_page: Optional[int] = None
    # Explicit sort/direction for stable pagination. Only set where the endpoint documents a sort enum.
    sort: Optional[str] = None
    direction: Optional[str] = None
    # Stable datetime field to partition on. Never use updated_at (it changes and rewrites partitions).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Top-level, account-scoped endpoints (all require account_id as a path segment). We ship full refresh
# for every endpoint: Drip's only documented server-side timestamp filter is `subscribed_after` on
# subscribers, which filters on subscription (creation) date and so would silently miss updates to
# existing subscribers — not a safe incremental cursor. See PR notes.
DRIP_ENDPOINTS: dict[str, DripEndpointConfig] = {
    "subscribers": DripEndpointConfig(
        name="subscribers",
        path="/subscribers",
        data_key="subscribers",
        primary_keys=["id"],
        per_page=1000,  # documented max for this endpoint
        partition_key="created_at",
    ),
    "campaigns": DripEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_key="campaigns",
        primary_keys=["id"],
        per_page=100,
        sort="created_at",
        direction="asc",
    ),
    "broadcasts": DripEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        data_key="broadcasts",
        primary_keys=["id"],
        per_page=100,
        sort="created_at",
        direction="asc",
    ),
    "workflows": DripEndpointConfig(
        name="workflows",
        path="/workflows",
        data_key="workflows",
        primary_keys=["id"],
        per_page=100,
    ),
    "forms": DripEndpointConfig(
        name="forms",
        path="/forms",
        data_key="forms",
        primary_keys=["id"],
    ),
    "goals": DripEndpointConfig(
        name="goals",
        path="/goals",
        data_key="goals",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(DRIP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DRIP_ENDPOINTS.items()
}
