from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
    SortMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Copper records expose `date_created` and `date_modified` as Unix epoch seconds (integers).
DATE_MODIFIED = "date_modified"
DATE_CREATED = "date_created"
ACTIVITY_DATE = "activity_date"
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

# `/activities/search` filters on the activity date only — it has no modified/created filter.
INCREMENTAL_FIELDS_ACTIVITY_DATE: list[IncrementalField] = [
    {
        "label": ACTIVITY_DATE,
        "type": IncrementalFieldType.Integer,
        "field": ACTIVITY_DATE,
        "field_type": IncrementalFieldType.Integer,
    },
]

# Inclusive minimum-date params the record search endpoints accept, per advertised incremental field.
SEARCH_INCREMENTAL_PARAMS = {
    DATE_MODIFIED: "minimum_modified_date",
    DATE_CREATED: "minimum_created_date",
}
ACTIVITY_INCREMENTAL_PARAMS = {ACTIVITY_DATE: "minimum_activity_date"}


@frozen
class CopperEndpointConfig:
    name: str
    path: str
    # Copper's record lists are POST `/search` endpoints; reference data is plain GET.
    method: Literal["GET", "POST"] = "POST"
    # GET reference endpoints return the full collection in one unpaginated array.
    paginated: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps each advertised incremental field to the search body's inclusive minimum-date param.
    incremental_params: dict[str, str] = field(default_factory=dict)
    # Search param capping the window at the sync's start time, for endpoints whose incremental
    # field the customer can edit.
    incremental_ceiling_param: str | None = None
    # Stable creation timestamp used for partitioning (never `date_modified`).
    partition_keys: list[str] | None = None
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    primary_keys: list[str] = field(default_factory=lambda: [ID])
    # Whether the search body accepts `sort_by` / `sort_direction`.
    sortable: bool = True
    # Sort field applied on full-refresh syncs to keep pagination stable.
    full_refresh_sort: str | None = DATE_CREATED
    sort_mode: SortMode = "asc"
    # Set when the response wraps rows in an envelope instead of returning a bare array.
    data_selector: str | None = None
    # Rows come from a custom iterator in `copper.py`; `path` is then a template that iterator
    # formats per request, not a complete request path.
    custom_iterator: bool = False


def _searchable(name: str, path: str) -> CopperEndpointConfig:
    return CopperEndpointConfig(
        name=name,
        path=path,
        method="POST",
        paginated=True,
        incremental_fields=INCREMENTAL_FIELDS_MODIFIED_CREATED,
        incremental_params=SEARCH_INCREMENTAL_PARAMS,
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


FIELD_LAYOUTS_ENDPOINT = "field_layouts"
RELATED_ITEMS_ENDPOINT = "related_items"

# Entity types Copper lets users configure field layouts for, spelled as the path wants them.
FIELD_LAYOUT_ENTITIES: tuple[str, ...] = ("people", "companies", "leads", "opportunities", "projects", "tasks")
# Only opportunity layouts are pipeline-specific.
FIELD_LAYOUT_PIPELINED_ENTITY = "opportunities"
# Stands in for "this layout is not pipeline-specific". A null would leave the column all-null on an
# account with no pipelines, and the next sync that found one would change the column's type.
FIELD_LAYOUT_NO_PIPELINE = 0

# Entity types Copper can relate to each other, as (the singular name it reports in a related row,
# the endpoint whose records we walk to collect those rows).
RELATED_ITEM_PARENTS: tuple[tuple[str, str], ...] = (
    ("lead", "leads"),
    ("person", "people"),
    ("company", "companies"),
    ("opportunity", "opportunities"),
    ("project", "projects"),
    ("task", "tasks"),
)

COPPER_ENDPOINTS: dict[str, CopperEndpointConfig] = {
    # Core CRM records: POST `/search`, page-based pagination, server-side timestamp filtering.
    "people": _searchable("people", "/people/search"),
    "companies": _searchable("companies", "/companies/search"),
    "leads": _searchable("leads", "/leads/search"),
    "opportunities": _searchable("opportunities", "/opportunities/search"),
    "projects": _searchable("projects", "/projects/search"),
    "tasks": _searchable("tasks", "/tasks/search"),
    # Activities: the CRM interaction log. Same page-based search, but it takes no sort params and
    # answers newest-first, and the only server-side filter is on `activity_date`. That date is
    # user-editable, so the window is capped at the sync's start time: one activity dated years
    # ahead would otherwise become the watermark and hide every later activity behind it. An
    # activity backdated below the watermark still needs a full refresh to appear.
    "activities": CopperEndpointConfig(
        name="activities",
        path="/activities/search",
        method="POST",
        paginated=True,
        incremental_fields=INCREMENTAL_FIELDS_ACTIVITY_DATE,
        incremental_params=ACTIVITY_INCREMENTAL_PARAMS,
        incremental_ceiling_param="maximum_activity_date",
        partition_keys=[DATE_CREATED],
        partition_mode="datetime",
        partition_format="week",
        sortable=False,
        full_refresh_sort=None,
        sort_mode="desc",
    ),
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
    "pipeline_stages": _reference("pipeline_stages", "/pipeline_stages"),
    "customer_sources": _reference("customer_sources", "/customer_sources"),
    "loss_reasons": _reference("loss_reasons", "/loss_reasons"),
    "contact_types": _reference("contact_types", "/contact_types"),
    "lead_statuses": _reference("lead_statuses", "/lead_statuses"),
    "custom_activity_types": _reference("custom_activity_types", "/custom_activity_types"),
    # Activity types come back grouped under "user" and "system" instead of as a bare array, and the
    # two categories share an id space (system "Property Changed" is id 1, and custom types are
    # numbered from 1 too), so the category has to be part of the key.
    "activity_types": CopperEndpointConfig(
        name="activity_types",
        path="/activity_types",
        method="GET",
        paginated=False,
        primary_keys=[ID, "category"],
        full_refresh_sort=None,
        data_selector="$.*[*]",
    ),
    "custom_field_definitions": _reference("custom_field_definitions", "/custom_field_definitions"),
    # Tags carry no id — the name is the identity, and Copper returns them sorted by name already.
    "tags": CopperEndpointConfig(
        name="tags",
        path="/tags",
        method="GET",
        paginated=False,
        primary_keys=["name"],
        full_refresh_sort=None,
    ),
    # Field layouts: one GET per entity type, plus one per pipeline for opportunities, whose layout
    # Copper varies by pipeline and refuses to return without a `pipeline_id`.
    FIELD_LAYOUTS_ENDPOINT: CopperEndpointConfig(
        name=FIELD_LAYOUTS_ENDPOINT,
        path="/field_layouts/by_entity/{entity}",
        method="GET",
        paginated=False,
        custom_iterator=True,
        primary_keys=["entity_type", "pipeline_id", "field_id"],
        full_refresh_sort=None,
    ),
    # Related items: the cross-object junction. Copper exposes it per record only, so this walks
    # every relatable record and asks for its edges. Relationships are bidirectional, so each edge
    # arrives twice, once from each end.
    RELATED_ITEMS_ENDPOINT: CopperEndpointConfig(
        name=RELATED_ITEMS_ENDPOINT,
        path="/{entity}/{record_id}/related",
        method="GET",
        paginated=False,
        custom_iterator=True,
        primary_keys=["parent_type", "parent_id", "type", "id"],
        full_refresh_sort=None,
    ),
}

ENDPOINTS = tuple(COPPER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COPPER_ENDPOINTS.items()
}
