from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class ShortcutEndpointConfig:
    name: str
    path: str
    # The flat list endpoints are plain GETs that return the whole collection. Stories have
    # no top-level list endpoint, so they're fetched via `POST /stories/search`.
    method: Literal["GET", "POST"] = "GET"
    primary_key: str = "id"
    # Stable field used for datetime partitioning. Never `updated_at` — partitions must not move.
    partition_key: Optional[str] = "created_at"
    # Map of incremental field name -> the server-side timestamp filter param it maps to.
    # Empty for full-refresh endpoints. Shortcut's flat list endpoints expose no server-side
    # timestamp filter (verified against the v3 OpenAPI spec), so only `stories` is incremental.
    incremental_params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    fanout: DependentEndpointConfig | None = None
    single_object: bool = False
    page_size: int = 100
    default_incremental_field: str | None = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Endpoint catalog. All flat collections are full-refresh: the Shortcut v3 API returns each
# in a single un-paginated response and accepts no server-side timestamp filter, so there is
# nothing to page through or filter incrementally. `stories` is the exception — it's queried
# through `POST /stories/search`, which accepts real server-side `created_at_start` /
# `updated_at_start` filters.
SHORTCUT_ENDPOINTS: dict[str, ShortcutEndpointConfig] = {
    "members": ShortcutEndpointConfig(name="members", path="/members"),
    "groups": ShortcutEndpointConfig(name="groups", path="/groups"),
    "projects": ShortcutEndpointConfig(name="projects", path="/projects"),
    "workflows": ShortcutEndpointConfig(name="workflows", path="/workflows"),
    "epics": ShortcutEndpointConfig(name="epics", path="/epics"),
    "iterations": ShortcutEndpointConfig(name="iterations", path="/iterations"),
    "labels": ShortcutEndpointConfig(name="labels", path="/labels"),
    "categories": ShortcutEndpointConfig(name="categories", path="/categories"),
    "objectives": ShortcutEndpointConfig(name="objectives", path="/objectives"),
    "custom_fields": ShortcutEndpointConfig(name="custom_fields", path="/custom-fields"),
    "files": ShortcutEndpointConfig(name="files", path="/files"),
    "linked_files": ShortcutEndpointConfig(name="linked_files", path="/linked-files"),
    "repositories": ShortcutEndpointConfig(name="repositories", path="/repositories"),
    "entity_templates": ShortcutEndpointConfig(name="entity_templates", path="/entity-templates"),
    "epic_workflow": ShortcutEndpointConfig(name="epic_workflow", path="/epic-workflow", single_object=True),
    "documents": ShortcutEndpointConfig(name="documents", path="/documents", partition_key=None),
    "story_history": ShortcutEndpointConfig(
        name="story_history",
        path="/stories/{story_id}/history",
        partition_key="changed_at",
        fanout=DependentEndpointConfig(
            parent_name="stories",
            resolve_param="story_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "story_id"},
        ),
    ),
    "epic_comments": ShortcutEndpointConfig(
        name="epic_comments",
        path="/epics/{epic_id}/comments",
        fanout=DependentEndpointConfig(
            parent_name="epics",
            resolve_param="epic_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "epic_id"},
        ),
    ),
    "stories": ShortcutEndpointConfig(
        name="stories",
        path="/stories/search",
        method="POST",
        incremental_params={
            "updated_at": "updated_at_start",
            "created_at": "created_at_start",
        },
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
    ),
}

ENDPOINTS = tuple(SHORTCUT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHORTCUT_ENDPOINTS.items()
}
