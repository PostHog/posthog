from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class EventeeEndpointConfig:
    name: str
    # Path under https://api.eventee.com/public/v1.
    path: str
    # When the endpoint returns a JSON object bundling several lists (the `/content` endpoint
    # carries halls/lectures/workshops/pauses/speakers/tracks), the rows for this table live under
    # this key. `None` means the response body is itself the list of rows (or a single object).
    data_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, creation-time field to partition on. Never an `updated_at`-style field — those rewrite
    # partitions on every sync. `None` for resources that expose no stable timestamp.
    partition_key: Optional[str] = None
    should_sync_default: bool = True


# Eventee's public API exposes a handful of read endpoints scoped to a single event by the Bearer
# token. `/content` returns one object bundling the agenda resources, so each of those becomes its own
# table sourced from the same call; the rest return their rows directly. No endpoint documents a
# server-side timestamp filter or pagination, so every table is full refresh only.
EVENTEE_ENDPOINTS: dict[str, EventeeEndpointConfig] = {
    "halls": EventeeEndpointConfig(name="halls", path="/content", data_key="halls", partition_key="created_at"),
    "lectures": EventeeEndpointConfig(
        name="lectures", path="/content", data_key="lectures", partition_key="created_at"
    ),
    "workshops": EventeeEndpointConfig(
        name="workshops", path="/content", data_key="workshops", partition_key="created_at"
    ),
    "pauses": EventeeEndpointConfig(name="pauses", path="/content", data_key="pauses", partition_key="created_at"),
    # Speakers and tracks expose no created_at/updated_at, so there's nothing stable to partition on.
    "speakers": EventeeEndpointConfig(name="speakers", path="/content", data_key="speakers"),
    "tracks": EventeeEndpointConfig(name="tracks", path="/content", data_key="tracks"),
    "reviews": EventeeEndpointConfig(name="reviews", path="/reviews", partition_key="created_at"),
    "groups": EventeeEndpointConfig(name="groups", path="/groups"),
    "participants": EventeeEndpointConfig(name="participants", path="/participants", partition_key="registered_at"),
    "partners": EventeeEndpointConfig(name="partners", path="/partners"),
    "registrations": EventeeEndpointConfig(name="registrations", path="/registrations"),
}

ENDPOINTS = tuple(EVENTEE_ENDPOINTS.keys())

# Eventee has no server-side timestamp filter (`since` / `_gte` / `modified_after`) on any endpoint,
# so nothing is incremental — the map is kept (empty) to mirror the other sources' shape and make
# adding a filterable endpoint later an additive change.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in EVENTEE_ENDPOINTS}
