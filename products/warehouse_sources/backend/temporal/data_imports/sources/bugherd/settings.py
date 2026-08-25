from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BUGHERD_BASE_URL = "https://www.bugherd.com"

# Tasks is the only endpoint that fans out from Projects today.
PROJECT_ID_FANOUT = DependentEndpointConfig(
    parent_name="Projects",
    resolve_param="project_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "project_id"},
)


@dataclass
class BugherdEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: str | list[str] = "id"
    # BugHerd list endpoints return a fixed ~100 rows/page with no client-configurable
    # size param, so `page_size` is unused (kept only to satisfy the fan-out helper's
    # structural typing) and `paginated=False` is only for the single-object Organization
    # endpoint.
    page_size: int = 100
    paginated: bool = True
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Maps an advertised incremental field name to the query param BugHerd's API actually
    # filters on for it (e.g. `updated_at` -> `updated_since`).
    incremental_query_params: dict[str, str] = field(default_factory=dict)
    sort_mode: Literal["asc", "desc"] = "asc"
    fanout: DependentEndpointConfig | None = None


BUGHERD_ENDPOINTS: dict[str, BugherdEndpointConfig] = {
    "Organization": BugherdEndpointConfig(
        name="Organization",
        path="/api_v2/organization.json",
        data_selector="organization",
        paginated=False,
    ),
    # Small, full-refresh dimension table. BugHerd documents an `updated_since` filter on
    # this endpoint, but the User response schema exposes no timestamp field to checkpoint
    # a watermark from, so we sync it in full each run rather than risk a cursor that never
    # advances.
    "Users": BugherdEndpointConfig(
        name="Users",
        path="/api_v2/users.json",
        data_selector="users",
    ),
    "Projects": BugherdEndpointConfig(
        name="Projects",
        path="/api_v2/projects.json",
        data_selector="projects",
        partition_key="created_at",
    ),
    "Tasks": BugherdEndpointConfig(
        name="Tasks",
        path="/api_v2/projects/{project_id}/tasks.json",
        data_selector="tasks",
        # `id` is the globally unique task ID (see the "Show Task (Global)" endpoint, which
        # looks tasks up by this field alone), unique across every project -- no composite
        # key needed even though this is a fan-out child.
        primary_key="id",
        partition_key="created_at",
        incremental_fields=[
            incremental_field("updated_at"),
            incremental_field("created_at"),
        ],
        default_incremental_field="updated_at",
        incremental_query_params={"updated_at": "updated_since", "created_at": "created_since"},
        # BugHerd's docs don't state a default sort order for this endpoint. Pagination is
        # page-number based (not a cursor token), so the `updated_since`/`created_since`
        # filter -- part of the base request params, not paginator state -- stays in effect
        # on every page regardless of ordering; an unconfirmed sort only risks uneven
        # batching, not a corrupted watermark.
        fanout=PROJECT_ID_FANOUT,
    ),
}

ENDPOINTS = tuple(BUGHERD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUGHERD_ENDPOINTS.items()
}
