from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

PAGE_SIZE = 100

PROJECT_FANOUT = DependentEndpointConfig(
    parent_name="projects",
    resolve_param="project_id",
    resolve_field="project_id",
    include_from_parent=["project_id"],
    parent_field_renames={"project_id": "project_id"},
)


@frozen
class LokaliseEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    pagination: Literal["page", "cursor"] = "page"
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = PROJECT_FANOUT


# The documented list methods have no timestamp filter, so cursor pagination resumes full refreshes only.
# https://developers.lokalise.com/reference/api-pagination
LOKALISE_ENDPOINTS = {
    "projects": LokaliseEndpointConfig(name="projects", path="/projects", primary_keys=["project_id"], fanout=None),
    "keys": LokaliseEndpointConfig(
        name="keys", path="/projects/{project_id}/keys", primary_keys=["project_id", "key_id"], pagination="cursor"
    ),
    "translations": LokaliseEndpointConfig(
        name="translations",
        path="/projects/{project_id}/translations",
        primary_keys=["project_id", "translation_id"],
        pagination="cursor",
    ),
    "languages": LokaliseEndpointConfig(
        name="languages", path="/projects/{project_id}/languages", primary_keys=["project_id", "lang_id"]
    ),
    "contributors": LokaliseEndpointConfig(
        name="contributors", path="/projects/{project_id}/contributors", primary_keys=["project_id", "user_id"]
    ),
    "comments": LokaliseEndpointConfig(
        name="comments", path="/projects/{project_id}/comments", primary_keys=["project_id", "comment_id"]
    ),
    "screenshots": LokaliseEndpointConfig(
        name="screenshots", path="/projects/{project_id}/screenshots", primary_keys=["project_id", "screenshot_id"]
    ),
    "tasks": LokaliseEndpointConfig(
        name="tasks", path="/projects/{project_id}/tasks", primary_keys=["project_id", "task_id"]
    ),
}
