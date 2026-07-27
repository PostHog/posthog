from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ProductboardEndpointConfig:
    name: str
    path: str
    # Set for endpoints served by the generic `/entities` resource; the value is the
    # `type[]` query param Productboard expects (e.g. "feature", "component").
    entity_type: Optional[str] = None
    primary_key: str = "id"
    # Stable, immutable datetime field used for partitioning. Never use `updatedAt`.
    partition_key: Optional[str] = None
    sort_mode: SortMode = "asc"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field name to the server-side filter query param that
    # actually filters on it (only the notes endpoint exposes such filters).
    incremental_param_map: dict[str, str] = field(default_factory=dict)
    default_incremental_field: Optional[str] = None

    @property
    def supports_incremental(self) -> bool:
        return bool(self.incremental_param_map)


_DATETIME = IncrementalFieldType.DateTime


def _datetime_field(name: str) -> IncrementalField:
    return {"label": name, "type": _DATETIME, "field": name, "field_type": _DATETIME}


# Notes are the only Productboard resource exposing server-side timestamp filters
# (`createdFrom` / `updatedFrom`). The list is sorted by creation date newest-first
# and there is no sort parameter, so we read it descending.
_NOTES = ProductboardEndpointConfig(
    name="notes",
    path="/notes",
    partition_key="createdAt",
    sort_mode="desc",
    incremental_fields=[_datetime_field("createdAt"), _datetime_field("updatedAt")],
    incremental_param_map={"createdAt": "createdFrom", "updatedAt": "updatedFrom"},
    default_incremental_field="updatedAt",
)


def _entity_endpoint(name: str, entity_type: str) -> ProductboardEndpointConfig:
    # Entity responses carry top-level `id`, `createdAt` and `updatedAt`, but the
    # `/entities` list endpoint exposes no timestamp filter, so these are full-refresh
    # only. `createdAt` is immutable, so it's a safe partition key.
    return ProductboardEndpointConfig(
        name=name,
        path="/entities",
        entity_type=entity_type,
        partition_key="createdAt",
    )


PRODUCTBOARD_ENDPOINTS: dict[str, ProductboardEndpointConfig] = {
    "features": _entity_endpoint("features", "feature"),
    "subfeatures": _entity_endpoint("subfeatures", "subfeature"),
    "components": _entity_endpoint("components", "component"),
    "products": _entity_endpoint("products", "product"),
    "initiatives": _entity_endpoint("initiatives", "initiative"),
    "objectives": _entity_endpoint("objectives", "objective"),
    "key_results": _entity_endpoint("key_results", "keyResult"),
    "releases": _entity_endpoint("releases", "release"),
    "release_groups": _entity_endpoint("release_groups", "releaseGroup"),
    "companies": _entity_endpoint("companies", "company"),
    "users": _entity_endpoint("users", "user"),
    "notes": _NOTES,
    # Members carry no documented top-level timestamp, so no partitioning.
    "members": ProductboardEndpointConfig(name="members", path="/members"),
    "teams": ProductboardEndpointConfig(name="teams", path="/teams", partition_key="createdAt"),
}

ENDPOINTS = tuple(PRODUCTBOARD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PRODUCTBOARD_ENDPOINTS.items()
}
