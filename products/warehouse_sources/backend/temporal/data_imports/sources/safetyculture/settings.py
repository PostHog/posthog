from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _modified_at_incremental_fields() -> list[IncrementalField]:
    # SafetyCulture's only server-side time filter is `modified_after`, which keys off `modified_at`.
    # Advertising just `modified_at` keeps the user's chosen cursor aligned with what the API filters on.
    return [
        {
            "label": "modified_at",
            "type": IncrementalFieldType.DateTime,
            "field": "modified_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class SafetyCultureEndpointConfig:
    name: str
    path: str  # Path under https://api.safetyculture.io, e.g. "/feed/inspections"
    # The feed documents a `modified_after` query param that filters server-side on `modified_at`.
    supports_incremental: bool
    # Static query params sent on the first request only — every later page comes from the verbatim
    # `metadata.next_page` path, which already carries them.
    params: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field to partition by. None when the feed exposes no created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Every data feed row carries a feed-unique `id` (e.g. inspection_items' `id` is the combined
    # inspection item ID, distinct from the per-template `item_id`).
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# SafetyCulture Data Feed endpoints (https://developer.safetyculture.com/reference/data-feeds) —
# the bulk-extraction API SafetyCulture recommends for warehouse syncs. Every feed returns
# {"metadata": {"next_page", "remaining_records"}, "data": [...]}; the `next_page` path must be
# followed verbatim. `archived`/`completed` are passed as "both" so the warehouse holds everything
# and users filter on the corresponding columns instead.
SAFETYCULTURE_ENDPOINTS: dict[str, SafetyCultureEndpointConfig] = {
    "inspections": SafetyCultureEndpointConfig(
        name="inspections",
        path="/feed/inspections",
        supports_incremental=True,
        params={"archived": "both", "completed": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "inspection_items": SafetyCultureEndpointConfig(
        name="inspection_items",
        path="/feed/inspection_items",
        supports_incremental=True,
        params={"archived": "both", "completed": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "templates": SafetyCultureEndpointConfig(
        name="templates",
        path="/feed/templates",
        supports_incremental=True,
        params={"archived": "both"},
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "actions": SafetyCultureEndpointConfig(
        name="actions",
        path="/feed/actions",
        supports_incremental=True,
        incremental_fields=_modified_at_incremental_fields(),
    ),
    "issues": SafetyCultureEndpointConfig(
        name="issues",
        path="/feed/issues",
        # The issues feed documents no `modified_after` param, so it's full refresh only.
        supports_incremental=False,
    ),
    "assets": SafetyCultureEndpointConfig(
        name="assets",
        path="/feed/assets",
        supports_incremental=False,
    ),
    "users": SafetyCultureEndpointConfig(
        name="users",
        path="/feed/users",
        supports_incremental=False,
    ),
    "groups": SafetyCultureEndpointConfig(
        name="groups",
        path="/feed/groups",
        supports_incremental=False,
        partition_key=None,
    ),
    "sites": SafetyCultureEndpointConfig(
        name="sites",
        path="/feed/sites",
        supports_incremental=False,
        partition_key=None,
    ),
    "schedules": SafetyCultureEndpointConfig(
        name="schedules",
        path="/feed/schedules",
        supports_incremental=False,
        # The schedules feed exposes `modified_at` but no `created_at`, so there is no stable
        # partition key.
        partition_key=None,
    ),
}

ENDPOINTS = tuple(SAFETYCULTURE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SAFETYCULTURE_ENDPOINTS.items()
}
