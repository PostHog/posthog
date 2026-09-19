from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# CodeScene's list endpoints take a generic `filter` expression but no server-side timestamp
# filter, so every endpoint here is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


@frozen
class CodesceneEndpointConfig:
    name: str
    path: str
    # Key holding the row array in the response body (e.g. `{"projects": [...], "max_pages": 3}`).
    # `None` for an endpoint that returns a bare array with no envelope.
    data_selector: str | None
    primary_key: str | list[str] = "id"
    page_size: int = 100
    # The endpoints differ in what they page on: most take `page` + `page_size` and report
    # `max_pages`, `analyses` pages on `page` alone, and `author-statistics` returns the whole
    # collection in a single unpaginated response.
    paginated: bool = True
    page_size_param: str | None = "page_size"
    fanout: DependentEndpointConfig | None = None
    # No endpoint here has a documented server-side timestamp filter, so every stream is full
    # refresh; these stay empty but satisfy the fan-out helper's endpoint protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


CODESCENE_ENDPOINTS: dict[str, CodesceneEndpointConfig] = {
    "Projects": CodesceneEndpointConfig(
        name="Projects",
        path="/projects",
        data_selector="projects",
        primary_key="id",
    ),
    "Files": CodesceneEndpointConfig(
        name="Files",
        path="/projects/{project_id}/analyses/latest/files",
        data_selector="files",
        primary_key=["project_id", "name"],
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
        ),
    ),
    "Components": CodesceneEndpointConfig(
        name="Components",
        path="/projects/{project_id}/analyses/latest/components",
        data_selector="components",
        primary_key=["project_id", "name"],
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
        ),
    ),
    "Analyses": CodesceneEndpointConfig(
        name="Analyses",
        path="/projects/{project_id}/analyses",
        data_selector="analyses",
        primary_key=["project_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
        ),
    ),
    "Issues": CodesceneEndpointConfig(
        name="Issues",
        path="/projects/{project_id}/analyses/latest/issues",
        data_selector="issues",
        primary_key=["project_id", "id"],
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
        ),
    ),
    "TechnicalDebt": CodesceneEndpointConfig(
        name="TechnicalDebt",
        path="/projects/{project_id}/analyses/latest/technical-debt",
        data_selector="result",
        primary_key=["project_id", "file_name"],
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
            # Without this the endpoint returns the friction summary rather than the
            # per-file refactoring targets.
            child_params={"refactoring_targets": "true"},
        ),
    ),
    "AuthorStatistics": CodesceneEndpointConfig(
        name="AuthorStatistics",
        path="/projects/{project_id}/analyses/latest/author-statistics",
        data_selector=None,
        primary_key=["project_id", "author"],
        paginated=False,
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "project_id"},
        ),
    ),
}

ENDPOINTS = tuple(CODESCENE_ENDPOINTS)
