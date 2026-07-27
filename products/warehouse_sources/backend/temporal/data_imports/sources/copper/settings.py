from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Copper records expose `date_created` and `date_modified` as Unix epoch seconds (integers).
DATE_MODIFIED = "date_modified"
DATE_CREATED = "date_created"
ID = "id"

# Copper caps `page_size` at 200 for the search endpoints.
COPPER_DEFAULT_PAGE_SIZE = 200

# Both timestamp fields arrive as integer Unix epoch seconds, so they're declared as integers.
INCREMENTAL_FIELDS_MODIFIED_CREATED: list[IncrementalField] = [
    {
        "label": DATE_MODIFIED,
        "type": IncrementalFieldType.Integer,
        "field": DATE_MODIFIED,
        "field_type": IncrementalFieldType.Integer,
    },
    {
        "label": DATE_CREATED,
        "type": IncrementalFieldType.Integer,
        "field": DATE_CREATED,
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass
class CopperEndpointConfig:
    name: str
    path: str
    # Copper's record lists are POST `/search` endpoints; reference data is plain GET.
    method: Literal["GET", "POST"] = "POST"
    # GET reference endpoints return the full collection in one unpaginated array.
    paginated: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for partitioning (never `date_modified`).
    partition_keys: list[str] | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    primary_key: str = ID
    # Sort field applied on full-refresh syncs to keep pagination stable.
    full_refresh_sort: str | None = DATE_CREATED


def _searchable(name: str, path: str) -> CopperEndpointConfig:
    return CopperEndpointConfig(
        name=name,
        path=path,
        method="POST",
        paginated=True,
        incremental_fields=INCREMENTAL_FIELDS_MODIFIED_CREATED,
        partition_keys=[DATE_CREATED],
        partition_mode="datetime",
        partition_format="week",
    )


def _reference(name: str, path: str) -> CopperEndpointConfig:
    return CopperEndpointConfig(
        name=name,
        path=path,
        method="GET",
        paginated=False,
        incremental_fields=[],
        full_refresh_sort=None,
    )


COPPER_ENDPOINTS: dict[str, CopperEndpointConfig] = {
    # Core CRM records: POST `/search`, page-based pagination, server-side timestamp filtering.
    "people": _searchable("people", "/people/search"),
    "companies": _searchable("companies", "/companies/search"),
    "leads": _searchable("leads", "/leads/search"),
    "opportunities": _searchable("opportunities", "/opportunities/search"),
    "projects": _searchable("projects", "/projects/search"),
    "tasks": _searchable("tasks", "/tasks/search"),
    # Users: paginated search but no reliable timestamp filter, so full refresh only.
    "users": CopperEndpointConfig(
        name="users",
        path="/users/search",
        method="POST",
        paginated=True,
        incremental_fields=[],
        full_refresh_sort=None,
    ),
    # Reference data: small unpaginated GET collections, useful for joins.
    "pipelines": _reference("pipelines", "/pipelines"),
    "customer_sources": _reference("customer_sources", "/customer_sources"),
    "loss_reasons": _reference("loss_reasons", "/loss_reasons"),
    "contact_types": _reference("contact_types", "/contact_types"),
}

ENDPOINTS = tuple(COPPER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COPPER_ENDPOINTS.items()
}
