from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every Rippling REST list endpoint supports the same standard query params
# (cursor/limit pagination, OData-style `filter`, `order_by` on id/created_at/
# updated_at), so the incremental menu is shared.
_STANDARD_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class RipplingEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_STANDARD_INCREMENTAL_FIELDS))
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None


RIPPLING_ENDPOINTS: dict[str, RipplingEndpointConfig] = {
    "workers": RipplingEndpointConfig(
        name="workers",
        path="/workers",
        partition_key="created_at",
    ),
    "users": RipplingEndpointConfig(
        name="users",
        path="/users",
        partition_key="created_at",
    ),
    "companies": RipplingEndpointConfig(
        name="companies",
        path="/companies",
    ),
    "departments": RipplingEndpointConfig(
        name="departments",
        path="/departments",
    ),
    "teams": RipplingEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "levels": RipplingEndpointConfig(
        name="levels",
        path="/levels",
    ),
    "work_locations": RipplingEndpointConfig(
        name="work_locations",
        path="/work-locations",
    ),
    "employment_types": RipplingEndpointConfig(
        name="employment_types",
        path="/employment-types",
    ),
    "compensations": RipplingEndpointConfig(
        name="compensations",
        path="/compensations",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(RIPPLING_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RIPPLING_ENDPOINTS.items() if config.incremental_fields
}
