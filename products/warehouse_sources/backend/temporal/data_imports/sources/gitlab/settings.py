from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class GitLabEndpointConfig:
    name: str
    path: str  # Path template with a {project} placeholder (project id or URL-encoded path)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Maps an incremental field name to the server-side query param that bounds it.
    # e.g. {"updated_at": "updated_after", "created_at": "created_after"} for issues/merge requests,
    # {"created_at": "since"} for commits. Only fields listed here actually filter server-side.
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    # Whether the list endpoint accepts order_by=<field>&sort=<dir>. When it does we pin the order
    # to a stable column so offset pages don't shift while we paginate.
    supports_order_by: bool = False
    # Column to order by on a full / first sync (must be a value the endpoint's order_by accepts).
    stable_order_by: Optional[str] = None
    partition_key: Optional[str] = None
    primary_key: str = "id"
    page_size: int = 100  # GitLab default & max per_page
    # The order rows are emitted in. Endpoints we sort ascending stay "asc"; commits cannot be
    # sorted server-side and always come newest-first, so they are "desc".
    sort_mode: Literal["asc", "desc"] = "asc"
    # Fan-out: name of the parent endpoint (issues / merge_requests) whose rows seed this child's
    # path. The child path carries a {parent_iid} placeholder filled from the parent's `iid`.
    fan_out_parent: Optional[str] = None
    # Column the parent's iid is injected into on every child row. Part of the primary key, since
    # the child API has no project-wide uniqueness guarantee we can rely on.
    fan_out_parent_column: Optional[str] = None


# Project-scoped endpoints. We cover the resources a user most commonly wants to analyze and that
# the canonical GitLab connectors (Airbyte/Fivetran) expose. Incremental support is only declared
# where a server-side timestamp filter actually drops rows (verified against the live API).
GITLAB_ENDPOINTS: dict[str, GitLabEndpointConfig] = {
    "issues": GitLabEndpointConfig(
        name="issues",
        path="/projects/{project}/issues",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="updated_at",
        incremental_filter_params={"updated_at": "updated_after", "created_at": "created_after"},
        supports_order_by=True,
        stable_order_by="created_at",
        partition_key="created_at",
    ),
    "merge_requests": GitLabEndpointConfig(
        name="merge_requests",
        path="/projects/{project}/merge_requests",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="updated_at",
        incremental_filter_params={"updated_at": "updated_after", "created_at": "created_after"},
        supports_order_by=True,
        stable_order_by="created_at",
        partition_key="created_at",
    ),
    "commits": GitLabEndpointConfig(
        name="commits",
        path="/projects/{project}/repository/commits",
        incremental_fields=[
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="created_at",
        # The commits endpoint exposes no order_by/sort; it always returns newest-first and only
        # accepts a `since` filter (bounded by commit/created date).
        incremental_filter_params={"created_at": "since"},
        supports_order_by=False,
        partition_key="created_at",
        sort_mode="desc",
    ),
    "pipelines": GitLabEndpointConfig(
        name="pipelines",
        path="/projects/{project}/pipelines",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
        ],
        default_incremental_field="updated_at",
        # Pipelines accept updated_after/updated_before; order_by does NOT accept created_at, only
        # updated_at (among id/status/ref/user_id), so updated_at is the stable order too.
        incremental_filter_params={"updated_at": "updated_after"},
        supports_order_by=True,
        stable_order_by="updated_at",
        partition_key="created_at",
    ),
    "releases": GitLabEndpointConfig(
        name="releases",
        path="/projects/{project}/releases",
        # No documented server-side timestamp filter -> full refresh only. Releases have no `id`;
        # tag_name is unique within a project.
        primary_key="tag_name",
        partition_key="created_at",
    ),
    "milestones": GitLabEndpointConfig(
        name="milestones",
        path="/projects/{project}/milestones",
        # No reliable server-side updated filter -> full refresh only.
        partition_key="created_at",
    ),
    "branches": GitLabEndpointConfig(
        name="branches",
        path="/projects/{project}/repository/branches",
        # Branches have no stable id/timestamp; name is the unique key. Full refresh.
        primary_key="name",
    ),
    "tags": GitLabEndpointConfig(
        name="tags",
        path="/projects/{project}/repository/tags",
        # Tag name is the unique key. created_at can be absent for some tags, so don't partition.
        primary_key="name",
    ),
    "labels": GitLabEndpointConfig(
        name="labels",
        path="/projects/{project}/labels",
    ),
    "members": GitLabEndpointConfig(
        name="members",
        path="/projects/{project}/members/all",
    ),
    "deployments": GitLabEndpointConfig(
        name="deployments",
        path="/projects/{project}/deployments",
        incremental_fields=[
            _datetime_incremental_field("updated_at"),
        ],
        default_incremental_field="updated_at",
        # GitLab rejects an updated_after filter unless the list is also ordered by updated_at,
        # which _build_initial_params does for the active incremental field.
        incremental_filter_params={"updated_at": "updated_after"},
        supports_order_by=True,
        stable_order_by="created_at",
        partition_key="created_at",
    ),
    # The fan-out children have no server-side time filter of their own. An incremental sync
    # instead bounds the parent walk with updated_after on the child watermark: creating a note or
    # a state event bumps the parent's updated_at, so only parents bumped since then are re-fanned.
    # Rows arrive grouped by parent rather than by created_at, hence "desc" (the watermark only
    # advances once the run completes). GitLab skips the parent touch for cross-reference system
    # notes ("mentioned in !12"), so an incremental sync picks those up only once the parent is next
    # updated; a full refresh collects them all.
    "issue_notes": GitLabEndpointConfig(
        name="issue_notes",
        path="/projects/{project}/issues/{parent_iid}/notes",
        incremental_fields=[
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="created_at",
        supports_order_by=True,
        stable_order_by="created_at",
        partition_key="created_at",
        sort_mode="desc",
        fan_out_parent="issues",
        fan_out_parent_column="issue_iid",
    ),
    "merge_request_notes": GitLabEndpointConfig(
        name="merge_request_notes",
        path="/projects/{project}/merge_requests/{parent_iid}/notes",
        incremental_fields=[
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="created_at",
        supports_order_by=True,
        stable_order_by="created_at",
        partition_key="created_at",
        sort_mode="desc",
        fan_out_parent="merge_requests",
        fan_out_parent_column="merge_request_iid",
    ),
    "issue_state_events": GitLabEndpointConfig(
        name="issue_state_events",
        path="/projects/{project}/issues/{parent_iid}/resource_state_events",
        incremental_fields=[
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="created_at",
        partition_key="created_at",
        sort_mode="desc",
        fan_out_parent="issues",
        fan_out_parent_column="issue_iid",
    ),
    "merge_request_state_events": GitLabEndpointConfig(
        name="merge_request_state_events",
        path="/projects/{project}/merge_requests/{parent_iid}/resource_state_events",
        incremental_fields=[
            _datetime_incremental_field("created_at"),
        ],
        default_incremental_field="created_at",
        partition_key="created_at",
        sort_mode="desc",
        fan_out_parent="merge_requests",
        fan_out_parent_column="merge_request_iid",
    ),
}

ENDPOINTS = tuple(GITLAB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITLAB_ENDPOINTS.items()
}
