from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION

# Simplecast's live REST API is labeled "2.0" (same https://api.simplecast.com host and Bearer
# auth the client already uses). UNVERSIONED_API_VERSION ("v1") is the framework placeholder that
# pre-versioning source rows carry; it maps to the same wire behaviour, so those syncs are
# unaffected. Header-based version selection is announced by Simplecast but not yet live, so both
# versions currently hit the one available API.
SIMPLECAST_API_VERSION_2_0 = "2.0"
SUPPORTED_VERSIONS = (UNVERSIONED_API_VERSION, SIMPLECAST_API_VERSION_2_0)
DEFAULT_VERSION = SIMPLECAST_API_VERSION_2_0


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
