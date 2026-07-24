from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# CodeScene has no documented server-side timestamp filter for these endpoints (the `analyses`
# list/detail shape isn't publicly documented), so every endpoint here is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


@dataclass
class CodesceneEndpointConfig:
    name: str
    path: str
    # Key holding the row array in the response body (e.g. `{"projects": [...], "max_pages": 3}`).
    data_selector: str
    primary_key: str | list[str] = "id"
    page_size: int = 100
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
}

ENDPOINTS = tuple(CODESCENE_ENDPOINTS)
