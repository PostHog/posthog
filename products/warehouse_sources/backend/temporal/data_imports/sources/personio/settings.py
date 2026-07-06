from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_UPDATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class PersonioEndpointConfig:
    name: str
    path: str
    # OAuth scope the endpoint needs (surfaced in the source caption).
    scope: str
    primary_key: str = "id"
    # Server-side updated_at filter param. Personio v2 is inconsistent per
    # endpoint: persons use strict `.gt`, the period endpoints use `.gte`.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Max page size the endpoint accepts (persons cap at 50, periods at 100).
    page_size: int = 100
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None


PERSONIO_ENDPOINTS: dict[str, PersonioEndpointConfig] = {
    "persons": PersonioEndpointConfig(
        name="persons",
        path="/v2/persons",
        scope="personio:persons:read",
        incremental_param="updated_at.gt",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
        page_size=50,
        partition_key="created_at",
    ),
    "absence_periods": PersonioEndpointConfig(
        name="absence_periods",
        path="/v2/absence-periods",
        scope="personio:absences:read",
        incremental_param="updated_at.gte",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
    "attendance_periods": PersonioEndpointConfig(
        name="attendance_periods",
        path="/v2/attendance-periods",
        scope="personio:attendances:read",
        incremental_param="updated_at.gte",
        incremental_fields=list(_UPDATED_AT_INCREMENTAL_FIELDS),
    ),
}

ENDPOINTS = tuple(PERSONIO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PERSONIO_ENDPOINTS.items() if config.incremental_fields
}
