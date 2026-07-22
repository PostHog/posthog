from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aha! caps `per_page` at 200 (default 30). Always request the max to minimise round trips.
PER_PAGE = 200


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # Aha!'s only server-side time filter is `updated_since`, which keys off `updated_at`.
    # Advertising just `updated_at` keeps the user's chosen cursor aligned with what the API filters on.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class AhaEndpointConfig:
    name: str
    path: str  # Path under /api/v1, e.g. "/features"
    # Root key of the list in the JSON response. Usually equals `path` minus the slash, but Aha!
    # exposes to-dos under `/tasks` with a `tasks` root key, so it's declared explicitly.
    response_key: str
    # Aha! exposes `updated_since` (filters by `updated_at`) on this endpoint's list action.
    supports_incremental: bool
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


AHA_ENDPOINTS: dict[str, AhaEndpointConfig] = {
    "products": AhaEndpointConfig(
        name="products",
        path="/products",
        response_key="products",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "features": AhaEndpointConfig(
        name="features",
        path="/features",
        response_key="features",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "epics": AhaEndpointConfig(
        name="epics",
        path="/epics",
        response_key="epics",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "initiatives": AhaEndpointConfig(
        name="initiatives",
        path="/initiatives",
        response_key="initiatives",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "ideas": AhaEndpointConfig(
        name="ideas",
        path="/ideas",
        response_key="ideas",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "goals": AhaEndpointConfig(
        name="goals",
        path="/goals",
        response_key="goals",
        # The Get goals list action documents no `updated_since` filter, so it's full refresh only.
        supports_incremental=False,
    ),
    "todos": AhaEndpointConfig(
        name="todos",
        path="/tasks",
        response_key="tasks",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "users": AhaEndpointConfig(
        name="users",
        path="/users",
        response_key="users",
        # The Get users list action only documents an `email` filter — no time-based incremental.
        supports_incremental=False,
    ),
}

ENDPOINTS = tuple(AHA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AHA_ENDPOINTS.items()
}
