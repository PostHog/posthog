from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BUGHERD_BASE_URL = "https://www.bugherd.com"

PROJECT_ID_FANOUT = DependentEndpointConfig(
    parent_name="Projects",
    resolve_param="project_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "project_id"},
)


@dataclass(frozen=True)
class BugherdChainedFanoutConfig:
    """A second-level fan-out whose child path binds several ids from one parent row.

    `build_dependent_resource` resolves a single path param from a single parent, so it
    cannot express `/projects/{project_id}/tasks/{task_id}/comments.json`, where both ids
    come from the same Tasks row. `parent_name` names an endpoint that is itself a fan-out
    child, so the built resource chain is Projects -> Tasks -> child.
    """

    parent_name: str
    # Child path param -> the field on the parent row it binds to.
    resolve_fields: dict[str, str]
    include_from_parent: list[str]
    parent_field_renames: dict[str, str]


TASK_COMMENTS_FANOUT = BugherdChainedFanoutConfig(
    parent_name="Tasks",
    resolve_fields={"project_id": "project_id", "task_id": "id"},
    include_from_parent=["id", "project_id"],
    parent_field_renames={"id": "task_id", "project_id": "project_id"},
)


@dataclass(frozen=True)
class BugherdEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_key: str | list[str] = "id"
    # BugHerd list endpoints return a fixed ~100 rows/page with no client-configurable
    # size param, so `page_size` is unused (kept only to satisfy the fan-out helper's
    # structural typing). `paginated=False` is for endpoints that return their whole
    # collection in one response and document no `page` param.
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
    chained_fanout: BugherdChainedFanoutConfig | None = None


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
    # Closed-out tasks live behind their own endpoint and never appear in `Tasks`, so
    # without this table completed work is missing entirely. It takes no `updated_since`
    # or `created_since` filter, hence full refresh.
    "ArchivedTasks": BugherdEndpointConfig(
        name="ArchivedTasks",
        path="/api_v2/projects/{project_id}/tasks/archive.json",
        data_selector="tasks",
        partition_key="created_at",
        fanout=PROJECT_ID_FANOUT,
    ),
    # The unsorted feedback inbox -- backlog tasks not yet promoted to the board. Also
    # takes no timestamp filter.
    "FeedbackTasks": BugherdEndpointConfig(
        name="FeedbackTasks",
        path="/api_v2/projects/{project_id}/tasks/feedback.json",
        data_selector="tasks",
        partition_key="created_at",
        fanout=PROJECT_ID_FANOUT,
    ),
    # Built-in and custom kanban columns, which resolve a task's `column_id`/`status_id`
    # to a board position. A project has a handful of columns and the endpoint documents
    # no `page` param, so it returns the whole collection in one response.
    "Columns": BugherdEndpointConfig(
        name="Columns",
        path="/api_v2/projects/{project_id}/columns.json",
        data_selector="columns",
        # Built-in columns (backlog, todo, doing, done) exist in every project and BugHerd
        # documents no global uniqueness for column IDs, so scope the key by project.
        primary_key=["project_id", "id"],
        paginated=False,
        fanout=PROJECT_ID_FANOUT,
    ),
    # The task discussion thread, and the only per-task event grain BugHerd exposes. The
    # endpoint carries no timestamp filter, and bounding the Tasks walk by `updated_since`
    # instead would assume a new comment bumps its task's `updated_at` -- which BugHerd
    # does not document (it fires `comment` and `task_update` as separate webhook events).
    # So full refresh, which re-walks every task each sync.
    "TaskComments": BugherdEndpointConfig(
        name="TaskComments",
        path="/api_v2/projects/{project_id}/tasks/{task_id}/comments.json",
        data_selector="comments",
        # The delete route addresses a comment by project and task as well as comment ID,
        # so treat the ID as task-scoped rather than global.
        primary_key=["task_id", "id"],
        partition_key="created_at",
        chained_fanout=TASK_COMMENTS_FANOUT,
    ),
}

ENDPOINTS = tuple(BUGHERD_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUGHERD_ENDPOINTS.items()
}
