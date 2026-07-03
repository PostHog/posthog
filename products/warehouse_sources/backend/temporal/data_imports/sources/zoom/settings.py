from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ZoomEndpointConfig:
    name: str
    # Path template relative to the Zoom API base. Fan-out endpoints contain a
    # ``{user_id}`` placeholder that is filled in per user (see ``fan_out``).
    path: str
    # Key in the JSON response body that holds the list of records
    # (e.g. ``{"users": [...], "next_page_token": "..."}``).
    data_key: str
    primary_key: str = "id"
    # A STABLE datetime field used for partitioning. Never use a field that
    # mutates over time (e.g. ``updated_at``) — partitions would be rewritten
    # on every sync.
    partition_key: Optional[str] = "created_at"
    # When True the endpoint is queried once per user returned by ``/users``.
    fan_out: bool = False
    # Static query params sent on every request to this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # Zoom caps ``page_size`` at 300 for these list endpoints.
    page_size: int = 300


# Zoom's list endpoints expose no server-side timestamp filter (no ``since`` /
# ``from`` on the meeting/webinar/user list endpoints), so every endpoint is a
# full refresh. ``created_at`` is declared as a partition key for stable
# partitioning but not as an incremental cursor — see ``get_schemas``.
ZOOM_ENDPOINTS: dict[str, ZoomEndpointConfig] = {
    "users": ZoomEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        primary_key="id",
        partition_key="created_at",
    ),
    "meetings": ZoomEndpointConfig(
        name="meetings",
        path="/users/{user_id}/meetings",
        data_key="meetings",
        primary_key="id",
        partition_key="created_at",
        fan_out=True,
        # ``scheduled`` returns all of a user's stored scheduled meetings,
        # including recurring ones — the most complete list for ingestion.
        params={"type": "scheduled"},
    ),
    "webinars": ZoomEndpointConfig(
        name="webinars",
        path="/users/{user_id}/webinars",
        data_key="webinars",
        primary_key="id",
        partition_key="created_at",
        fan_out=True,
    ),
}

ENDPOINTS = tuple(ZOOM_ENDPOINTS.keys())

# No endpoint supports server-side incremental filtering, so this stays empty.
# Kept for parity with other sources and to make enabling incremental later a
# one-line change once Zoom exposes a usable filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
