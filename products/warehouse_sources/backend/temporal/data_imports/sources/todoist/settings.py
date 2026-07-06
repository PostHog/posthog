from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Todoist's unified v1 REST API. The legacy REST v2 (/rest/v2) and Sync v8/v9 endpoints are
# being shut down in early 2026, so everything here targets /api/v1.
TODOIST_BASE_URL = "https://api.todoist.com/api/v1"


@dataclass
class TodoistEndpointConfig:
    name: str
    path: str
    # Stable creation timestamp used to partition the Delta table. None when the resource exposes no
    # stable creation timestamp (e.g. labels, sections). Never use a mutable field like `updated_at`.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Fan out one paginated request per synced project, materializing the project<->collaborator
    # membership as rows. When True, `path` is a template with a `{project_id}` placeholder and the
    # synced project_id is injected onto every row.
    fan_out_over_projects: bool = False


TODOIST_ENDPOINTS: dict[str, TodoistEndpointConfig] = {
    "tasks": TodoistEndpointConfig(
        name="tasks",
        path="/tasks",
        # Raw v1 task objects carry `added_at` as the creation timestamp (the official SDK aliases it
        # to `created_at`). Verified against the published SDK model, not a live token.
        partition_key="added_at",
    ),
    "projects": TodoistEndpointConfig(
        name="projects",
        path="/projects",
        partition_key="created_at",
    ),
    "sections": TodoistEndpointConfig(
        name="sections",
        path="/sections",
    ),
    "labels": TodoistEndpointConfig(
        name="labels",
        path="/labels",
    ),
    # Project<->collaborator membership is only reachable per project, so this fans out one request
    # per synced project. The collaborator id is unique per person but a person can belong to many
    # projects, so the primary key is composite to stay unique table-wide.
    "collaborators": TodoistEndpointConfig(
        name="collaborators",
        path="/projects/{project_id}/collaborators",
        primary_keys=["project_id", "id"],
        # One paginated request per project, so it's opt-in (off by default) to avoid the extra API
        # cost for users who don't need project<->collaborator membership.
        should_sync_default=False,
        fan_out_over_projects=True,
    ),
}

ENDPOINTS = tuple(TODOIST_ENDPOINTS.keys())

# The v1 REST endpoints expose no server-side timestamp filter (no `since`/`updated_after`), so every
# endpoint is full refresh — there is no genuine incremental field to advertise. Incremental sync on
# Todoist is only possible through the separate /sync delta API, which this source does not use yet.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in TODOIST_ENDPOINTS}
