from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Lightdash documents no default/max page size for its paginated endpoints (org/users,
# dataCatalog/metrics); 100 keeps individual pages small without excessive round trips.
PAGE_SIZE = 100


@dataclass
class LightdashEndpointConfig:
    name: str
    path: str
    # jsonpath selector into the response body: every Lightdash list endpoint wraps its rows in
    # {"status": "ok", "results": ...} — "results" for a bare array, "results.data" for the
    # paginated {"data": [...], "pagination": {...}} shape.
    data_selector: str
    primary_key: str | list[str]
    # Lightdash has no server-side updated-since/created-since filter on any list endpoint, so
    # every stream is full-refresh only. Left empty; kept for the fan-out helper's endpoint protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Stable creation-time field used for datetime partitioning. Left None when the resource has no
    # reliably-present, non-mutating creation timestamp (spaces/dashboards/charts only expose
    # `updatedAt`, which the skill's partitioning rule excludes).
    partition_key: str | None = None
    paginated: bool = False
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None


LIGHTDASH_ENDPOINTS: dict[str, LightdashEndpointConfig] = {
    "projects": LightdashEndpointConfig(
        name="projects",
        path="/api/v1/org/projects",
        data_selector="results",
        primary_key="projectUuid",
        partition_key="createdAt",
    ),
    "spaces": LightdashEndpointConfig(
        name="spaces",
        path="/api/v1/projects/{projectUuid}/spaces",
        data_selector="results",
        # `uuid` is a Lightdash-generated identifier, globally unique by construction (not a
        # per-project sequential id), so no parent id is needed to keep it unique table-wide.
        primary_key="uuid",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectUuid",
            resolve_field="projectUuid",
            include_from_parent=["projectUuid"],
            # The framework injects the parent value under `_projects_projectUuid`; renaming it
            # back to `projectUuid` guarantees the column even if a future Lightdash response
            # ever omitted its own copy of the field.
            parent_field_renames={"projectUuid": "projectUuid"},
        ),
    ),
    "dashboards": LightdashEndpointConfig(
        name="dashboards",
        path="/api/v1/projects/{projectUuid}/dashboards",
        data_selector="results",
        primary_key="uuid",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectUuid",
            resolve_field="projectUuid",
            include_from_parent=["projectUuid"],
            # The framework injects the parent value under `_projects_projectUuid`; renaming it
            # back to `projectUuid` guarantees the column even if a future Lightdash response
            # ever omitted its own copy of the field.
            parent_field_renames={"projectUuid": "projectUuid"},
        ),
    ),
    "charts": LightdashEndpointConfig(
        name="charts",
        path="/api/v1/projects/{projectUuid}/charts",
        data_selector="results",
        primary_key="uuid",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectUuid",
            resolve_field="projectUuid",
            include_from_parent=["projectUuid"],
            # The framework injects the parent value under `_projects_projectUuid`; renaming it
            # back to `projectUuid` guarantees the column even if a future Lightdash response
            # ever omitted its own copy of the field.
            parent_field_renames={"projectUuid": "projectUuid"},
        ),
    ),
    "metrics_catalog": LightdashEndpointConfig(
        name="metrics_catalog",
        path="/api/v1/projects/{projectUuid}/dataCatalog/metrics",
        data_selector="results.data",
        primary_key="catalogSearchUuid",
        paginated=True,
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectUuid",
            resolve_field="projectUuid",
            include_from_parent=["projectUuid"],
            # The framework injects the parent value under `_projects_projectUuid`; renaming it
            # back to `projectUuid` guarantees the column even if a future Lightdash response
            # ever omitted its own copy of the field.
            parent_field_renames={"projectUuid": "projectUuid"},
        ),
    ),
    "org_users": LightdashEndpointConfig(
        name="org_users",
        path="/api/v1/org/users",
        data_selector="results.data",
        primary_key="userUuid",
        partition_key="userCreatedAt",
        paginated=True,
    ),
}

ENDPOINTS = tuple(LIGHTDASH_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LIGHTDASH_ENDPOINTS.items()
}
