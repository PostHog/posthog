from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Todoist's unified v1 REST API. The legacy REST v2 (/rest/v2) and Sync v8/v9 endpoints are
# being shut down in early 2026, so everything here targets /api/v1.
TODOIST_BASE_URL = "https://api.todoist.com/api/v1"


# Completed tasks are only listable inside a since/until range of at most 3 months. 89 days is the
# shortest 3 calendar months (February to April), so every window passes whichever way Todoist counts.
COMPLETED_TASKS_WINDOW = timedelta(days=89)
# Todoist launched in 2007, so no task was completed before this. A full sweep from here costs about
# 80 window requests, most of them empty.
COMPLETED_TASKS_EARLIEST = datetime(2007, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class TodoistFanOut:
    # The parent endpoint whose rows each produce one child request.
    parent: str
    # The column the parent's `id` is written to on every child row.
    parent_id_column: str
    resume_parent_pagination: bool = False


@dataclass(frozen=False)
class TodoistEndpointConfig:
    name: str
    path: str
    # Stable creation timestamp used to partition the Delta table. None when the resource exposes no
    # stable creation timestamp (e.g. labels, sections). Never use a mutable field like `updated_at`.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Fan out one paginated request per parent row. `path` then holds a placeholder named after
    # `parent_id_column`, and the parent id is written onto every row under that column.
    fan_out: Optional[TodoistFanOut] = None
    # The rows only exist inside since/until windows, which the source walks oldest first.
    completion_windows: bool = False
    # Query param that takes the incremental watermark, for endpoints with a server-side filter.
    incremental_param: Optional[str] = None


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
        fan_out=TodoistFanOut(parent="projects", parent_id_column="project_id"),
    ),
    # /tasks lists active tasks only. A recurring task keeps its id across completions, so the
    # completion time is part of the key to keep one row per completion.
    "completed_tasks": TodoistEndpointConfig(
        name="completed_tasks",
        path="/tasks/completed/by_completion_date",
        partition_key="completed_at",
        primary_keys=["id", "completed_at"],
        completion_windows=True,
    ),
    # Activity entries carry a nullable `id`, so the key uses the fields the API always returns.
    "activities": TodoistEndpointConfig(
        name="activities",
        path="/activities",
        partition_key="event_date",
        primary_keys=["object_type", "object_id", "event_type", "event_date"],
        incremental_param="date_from",
    ),
    # Comments are only listable per task or per project. Both fan-outs cost one request per parent,
    # so they are opt-in like collaborators.
    "comments": TodoistEndpointConfig(
        name="comments",
        path="/comments?task_id={task_id}",
        partition_key="posted_at",
        should_sync_default=False,
        fan_out=TodoistFanOut(parent="tasks", parent_id_column="task_id", resume_parent_pagination=True),
    ),
    "project_comments": TodoistEndpointConfig(
        name="project_comments",
        path="/comments?project_id={project_id}",
        partition_key="posted_at",
        should_sync_default=False,
        fan_out=TodoistFanOut(parent="projects", parent_id_column="project_id", resume_parent_pagination=True),
    ),
}

ENDPOINTS = tuple(TODOIST_ENDPOINTS.keys())


def _datetime_field(name: str) -> list[IncrementalField]:
    return [
        IncrementalField(
            label=name, type=IncrementalFieldType.DateTime, field=name, field_type=IncrementalFieldType.DateTime
        )
    ]


# Only the completed-task and activity endpoints take a server-side time filter (`since` and
# `date_from`). The other v1 list endpoints have none, so they stay full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: [] for name in TODOIST_ENDPOINTS},
    "completed_tasks": _datetime_field("completed_at"),
    "activities": _datetime_field("event_date"),
}
