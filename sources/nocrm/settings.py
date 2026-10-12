from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class NoCRMEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # True only when noCRM exposes a server-side change filter for this list endpoint. Today that's
    # just `/leads` via `updated_after`; every other endpoint is a small config/metadata list with no
    # timestamp filter, so it ships full refresh.
    supports_incremental: bool = False
    # Query param used for the server-side "changed since" filter (leads: `updated_after`).
    incremental_param: Optional[str] = None
    # `order` value that sorts the list ascending by the incremental field, so pages arrive in the
    # order the pipeline's `asc` watermark expects. Only set on incremental endpoints.
    incremental_sort_order: Optional[str] = None
    # `order` value for a stable ascending sort on full-refresh / non-incremental runs, guarding against
    # page-boundary skips if rows are inserted mid-sync. `None` means don't send an `order` param at all
    # (most metadata endpoints don't document one, so we avoid sending params they might reject).
    default_sort_order: Optional[str] = None
    # Stable creation timestamp used for datetime partitioning. None for small metadata endpoints with
    # no creation timestamp / not worth partitioning.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # noCRM's `updated_after` filters leads by their last-update time, so `updated_at` is the only
    # meaningful incremental cursor. `created_at` is used for partitioning, not incremental sync.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


NOCRM_ENDPOINTS: dict[str, NoCRMEndpointConfig] = {
    "leads": NoCRMEndpointConfig(
        name="leads",
        path="/leads",
        supports_incremental=True,
        incremental_param="updated_after",
        incremental_sort_order="last_update",
        default_sort_order="id",
        partition_key="created_at",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "activities": NoCRMEndpointConfig(
        name="activities",
        path="/activities",
        incremental_fields=[],
    ),
    "users": NoCRMEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[],
    ),
    "teams": NoCRMEndpointConfig(
        name="teams",
        path="/teams",
        incremental_fields=[],
    ),
    "steps": NoCRMEndpointConfig(
        name="steps",
        path="/steps",
        incremental_fields=[],
    ),
    "pipelines": NoCRMEndpointConfig(
        name="pipelines",
        path="/pipelines",
        incremental_fields=[],
    ),
    "client_folders": NoCRMEndpointConfig(
        name="client_folders",
        path="/clients",
        incremental_fields=[],
    ),
    "categories": NoCRMEndpointConfig(
        name="categories",
        path="/categories",
        incremental_fields=[],
    ),
    "tags": NoCRMEndpointConfig(
        name="tags",
        path="/predefined_tags",
        incremental_fields=[],
    ),
    "fields": NoCRMEndpointConfig(
        name="fields",
        path="/fields",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(NOCRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NOCRM_ENDPOINTS.items()
}
