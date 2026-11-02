from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# AfterShip pins the Tracking API version in the URL path (https://api.aftership.com/tracking/<version>)
# and ships a new dated version every six months. 2026-07 is the current generally available version
# and the one the official SDK targets, so every path below is built against it.
AFTERSHIP_2026_07 = "2026-07"
SUPPORTED_VERSIONS = (AFTERSHIP_2026_07,)
DEFAULT_VERSION = AFTERSHIP_2026_07

AFTERSHIP_BASE_URL = "https://api.aftership.com/tracking"

# Max page size accepted by both cursor-paginated list endpoints (default 100, max 200).
PAGE_SIZE = 200


@dataclass
class AftershipEndpointConfig:
    name: str
    """Table name we expose to the user."""
    path: str
    """API path relative to the versioned base URL."""
    data_selector: str
    """JSON path to the row array inside AfterShip's `{"meta": ..., "data": ...}` envelope."""
    primary_key: list[str]
    cursor_paginated: bool = True
    """Cursor pagination via `cursor` + `data.pagination.next_cursor`. False means a single page."""
    incremental_params: dict[str, str] = field(default_factory=dict)
    """Incremental field name -> the server-side "updated/created since" query param it maps to."""
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    """A STABLE field to partition on. Never an updated_at-style field, which would rewrite
    partitions on every sync."""
    extra_params: dict[str, Any] = field(default_factory=dict)
    """Static query params sent on every request for the endpoint."""


AFTERSHIP_ENDPOINTS: dict[str, AftershipEndpointConfig] = {
    # GET /trackings is the only endpoint with server-side time filters. Both `created_at_min` and
    # `updated_at_min` genuinely filter server-side, so either can back an incremental sync.
    #
    # Caveat worth knowing when reading synced data: AfterShip defaults `created_at_min` to 120 days
    # ago and documents that it only stores 120 days of trackings, so a sync never reaches further
    # back than that regardless of the sync type. We deliberately don't send a wider `created_at_min`
    # of our own — there is no documented behaviour for a window beyond the retention period.
    "trackings": AftershipEndpointConfig(
        name="trackings",
        path="/trackings",
        data_selector="data.trackings",
        primary_key=["id"],
        incremental_params={"updated_at": "updated_at_min", "created_at": "created_at_min"},
        incremental_fields=[incremental_field("updated_at"), incremental_field("created_at")],
        partition_key="created_at",
        extra_params={"limit": PAGE_SIZE},
    ),
    # GET /couriers returns the couriers activated on the account. It has no cursor and no time
    # filter, so it is a single-page full refresh keyed on the courier slug.
    "couriers": AftershipEndpointConfig(
        name="couriers",
        path="/couriers",
        data_selector="data.couriers",
        primary_key=["slug"],
        cursor_paginated=False,
    ),
    # GET /courier-connections is cursor paginated but exposes no time filter, so it stays full
    # refresh even though rows carry created_at/updated_at.
    "courier_connections": AftershipEndpointConfig(
        name="courier_connections",
        path="/courier-connections",
        data_selector="data.courier_connections",
        primary_key=["id"],
        extra_params={"limit": PAGE_SIZE},
    ),
}

ENDPOINTS = tuple(AFTERSHIP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AFTERSHIP_ENDPOINTS.items()
}
