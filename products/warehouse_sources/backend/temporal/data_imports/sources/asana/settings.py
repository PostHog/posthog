from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# How an endpoint's request URLs are derived (drives the rest_source resource chain):
#   "none"          -> a single top-level list endpoint (no parent fan-out)
#   "workspace"     -> one request per workspace the token can see
#   "organization"  -> one request per workspace that is an organization
#   "project"       -> one request per project across all visible workspaces
#   "task"          -> one request per task across all visible projects
#   "goal"          -> one request per goal across all visible workspaces
#   "user"          -> one request per user the token can see
FanOut = Literal["none", "workspace", "organization", "project", "task", "goal", "user"]

# Every Asana resource is identified by its global id ``gid``.
PRIMARY_KEY = "gid"


@frozen
class AsanaEndpointConfig:
    name: str
    fan_out: FanOut
    # Relative path appended to the API base. Fan-out endpoints carry a single ``{workspace_gid}``,
    # ``{project_gid}``, ``{task_gid}``, ``{goal_gid}`` or ``{user_gid}`` placeholder that the
    # framework binds from the parent row per request; top-level endpoints carry no placeholder.
    path: str
    # Asana list endpoints return compact records ({gid, name, resource_type}) by default.
    # ``opt_fields`` opts extra properties into the response — keep the partition key here.
    opt_fields: list[str] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Must be present in opt_fields.
    # Never a ``modified_at``-style field — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    # Fan-out parent fields to copy onto every row, mapped to the column they land in. Needed when
    # the row's own gid is not unique table-wide because the same object is returned under several
    # parents.
    parent_fields: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: [PRIMARY_KEY])
    # A few endpoints return the whole collection in one response — they take no limit/offset and
    # carry no `next_page`. Sending `limit` to those is rejected.
    paginated: bool = True


ASANA_ENDPOINTS: dict[str, AsanaEndpointConfig] = {
    "workspaces": AsanaEndpointConfig(
        name="workspaces",
        fan_out="none",
        path="/workspaces",
        opt_fields=["name", "email_domains", "is_organization", "resource_type"],
    ),
    "users": AsanaEndpointConfig(
        name="users",
        fan_out="none",
        path="/users",
        opt_fields=["name", "email", "photo", "workspaces", "resource_type"],
    ),
    "projects": AsanaEndpointConfig(
        name="projects",
        fan_out="workspace",
        path="/projects?workspace={workspace_gid}",
        opt_fields=[
            "name",
            "created_at",
            "modified_at",
            "archived",
            "color",
            "current_status",
            "default_view",
            "due_date",
            "due_on",
            "start_on",
            "notes",
            "public",
            "owner",
            "team",
            "workspace",
            "completed",
            "completed_at",
            "members",
            "followers",
            "permalink_url",
            "resource_type",
        ],
        partition_key="created_at",
    ),
    "project_memberships": AsanaEndpointConfig(
        name="project_memberships",
        fan_out="project",
        path="/projects/{project_gid}/project_memberships",
        opt_fields=["member", "access_level", "parent", "resource_type"],
    ),
    "tasks": AsanaEndpointConfig(
        name="tasks",
        fan_out="project",
        path="/tasks?project={project_gid}",
        opt_fields=[
            "name",
            "created_at",
            "modified_at",
            "completed",
            "completed_at",
            "due_on",
            "due_at",
            "start_on",
            "assignee",
            "assignee_status",
            "notes",
            "parent",
            "projects",
            "tags",
            "workspace",
            "resource_subtype",
            "num_hearts",
            "num_likes",
            "permalink_url",
            "custom_fields",
        ],
        partition_key="created_at",
    ),
    "stories": AsanaEndpointConfig(
        name="stories",
        fan_out="task",
        path="/tasks/{task_gid}/stories",
        opt_fields=[
            "created_at",
            "created_by",
            "resource_subtype",
            "resource_type",
            "text",
            "type",
            "source",
            "target",
            "task",
            "project",
            "tag",
            "assignee",
            "follower",
            "dependency",
            "duplicate_of",
            "duplicated_from",
            "custom_field",
            "is_pinned",
            "is_edited",
            "num_likes",
            "sticker_name",
            "old_name",
            "new_name",
            "old_section",
            "new_section",
            "old_dates",
            "new_dates",
            "old_resource_subtype",
            "new_resource_subtype",
            "old_approval_status",
            "new_approval_status",
            "old_text_value",
            "new_text_value",
            "old_number_value",
            "new_number_value",
            "old_date_value",
            "new_date_value",
            "old_enum_value",
            "new_enum_value",
            "old_multi_enum_values",
            "new_multi_enum_values",
            "old_people_value",
            "new_people_value",
        ],
        partition_key="created_at",
    ),
    "tags": AsanaEndpointConfig(
        name="tags",
        fan_out="workspace",
        path="/tags?workspace={workspace_gid}",
        opt_fields=["name", "created_at", "color", "notes", "workspace", "permalink_url", "resource_type"],
        partition_key="created_at",
    ),
    "sections": AsanaEndpointConfig(
        name="sections",
        fan_out="project",
        path="/projects/{project_gid}/sections",
        opt_fields=["name", "created_at", "project", "resource_type"],
        partition_key="created_at",
    ),
    "teams": AsanaEndpointConfig(
        name="teams",
        fan_out="organization",
        path="/organizations/{workspace_gid}/teams",
        opt_fields=["name", "description", "organization", "permalink_url", "visibility", "resource_type"],
    ),
    "custom_fields": AsanaEndpointConfig(
        name="custom_fields",
        fan_out="workspace",
        path="/workspaces/{workspace_gid}/custom_fields",
        opt_fields=[
            "name",
            "description",
            "type",
            "resource_subtype",
            "enabled",
            "format",
            "precision",
            "is_global_to_workspace",
            "created_by",
            "resource_type",
        ],
    ),
    "goals": AsanaEndpointConfig(
        name="goals",
        fan_out="workspace",
        path="/goals?workspace={workspace_gid}",
        opt_fields=[
            "name",
            "notes",
            "owner",
            "status",
            "due_on",
            "start_on",
            "is_workspace_level",
            "team",
            "workspace",
            "time_period",
            "metric",
            "current_status_update",
            "privacy_setting",
            "default_access_level",
            "followers",
            "num_likes",
            "custom_fields",
            "resource_type",
        ],
    ),
    # One row per goal-to-parent-goal edge. The row is the parent goal, so its gid repeats across
    # every child goal that points at it — `goal_gid` (the child) completes the primary key.
    "parent_goals": AsanaEndpointConfig(
        name="parent_goals",
        fan_out="goal",
        path="/goals/{goal_gid}/parentGoals",
        opt_fields=["name", "owner", "resource_type"],
        parent_fields={"gid": "goal_gid"},
        primary_keys=["goal_gid", PRIMARY_KEY],
        paginated=False,
    ),
    # User fan-out: /time_tracking_entries needs one of its filters, and `user` is the only one that
    # covers every entry without a date window (filtering by workspace requires an entered-on range).
    "time_tracking_entries": AsanaEndpointConfig(
        name="time_tracking_entries",
        fan_out="user",
        path="/time_tracking_entries?user={user_gid}",
        opt_fields=[
            "duration_minutes",
            "entered_on",
            "created_at",
            "created_by",
            "task",
            "attributable_to",
            "approval_status",
            "billable_status",
            "description",
            "resource_type",
        ],
        partition_key="created_at",
    ),
    # AI Studio usage endpoints (organization fan-out — AI Studio is an org/division feature, so
    # non-organization workspaces are skipped to avoid invalid requests). Both require the
    # `admin.ai_studio_usage:read` scope on an AI Studio-licensed org; unlicensed orgs return 403.
    "ai_studio_runs": AsanaEndpointConfig(
        name="ai_studio_runs",
        fan_out="organization",
        path="/workspaces/{workspace_gid}/ai_studio/runs",
        opt_fields=[
            "rule.name",
            "rule_owner.name",
            "rule_owner.email",
            "triggered_by.name",
            "triggered_by.email",
            "triggering_container.resource_type",
            "division.name",
            "run_started_at",
            "run_completed_at",
            "status",
            "model",
            "credits_used",
            "credit_source",
            "resource_type",
        ],
        partition_key="run_started_at",
    ),
    "ai_studio_seats": AsanaEndpointConfig(
        name="ai_studio_seats",
        fan_out="organization",
        path="/workspaces/{workspace_gid}/ai_studio/seats",
        opt_fields=[
            "user.name",
            "user.email",
            "license",
            "state",
            "assigned_at",
            "revoked_at",
            "assigned_by.name",
            "resource_type",
        ],
    ),
}

ENDPOINTS = tuple(ASANA_ENDPOINTS.keys())

# Asana exposes a server-side `modified_since` filter only on /tasks (and the premium-only
# task search endpoint). The other endpoints have no usable server-side timestamp filter, so
# the whole source ships full-refresh-only for now — declaring incremental support without a
# real server filter would make every "incremental" run cost the same as a full refresh.
# Incremental tasks (via `modified_since`) and the Events API are tracked as follow-ups; they
# need a live token to smoke-test the filter behaviour before we can rely on it.
# `ai_studio/runs` does take a `start_at`/`end_at` window, but it filters by an internal metering
# timestamp that the row shape does not expose — so no synced column maps cleanly onto the cursor,
# and the arrival order can't be verified without a live token. It stays full-refresh with the rest.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
