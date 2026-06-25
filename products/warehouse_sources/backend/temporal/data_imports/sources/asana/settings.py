from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# How an endpoint's request URLs are derived:
#   "none"          -> a single top-level list endpoint (no parent fan-out)
#   "workspace"     -> one request per workspace the token can see
#   "organization"  -> one request per workspace that is an organization
#   "project"       -> one request per project across all visible workspaces
FanOut = Literal["none", "workspace", "organization", "project"]


@dataclass
class AsanaEndpointConfig:
    name: str
    fan_out: FanOut
    # Relative path appended to the API base. Contains a single ``{gid}`` placeholder for
    # fan-out endpoints (the parent resource id), and no placeholder for top-level ones.
    path_template: str
    # Asana list endpoints return compact records ({gid, name, resource_type}) by default.
    # ``opt_fields`` opts extra properties into the response — keep the partition key here.
    opt_fields: list[str] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Must be present in opt_fields.
    # Never a ``modified_at``-style field — partitions would rewrite on every sync.
    partition_key: Optional[str] = None


# Every Asana resource is identified by its global id ``gid``.
PRIMARY_KEY = "gid"

ASANA_ENDPOINTS: dict[str, AsanaEndpointConfig] = {
    "workspaces": AsanaEndpointConfig(
        name="workspaces",
        fan_out="none",
        path_template="/workspaces",
        opt_fields=["name", "email_domains", "is_organization", "resource_type"],
    ),
    "users": AsanaEndpointConfig(
        name="users",
        fan_out="none",
        path_template="/users",
        opt_fields=["name", "email", "photo", "workspaces", "resource_type"],
    ),
    "projects": AsanaEndpointConfig(
        name="projects",
        fan_out="workspace",
        path_template="/projects?workspace={gid}",
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
    "tasks": AsanaEndpointConfig(
        name="tasks",
        fan_out="project",
        path_template="/tasks?project={gid}",
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
    "tags": AsanaEndpointConfig(
        name="tags",
        fan_out="workspace",
        path_template="/tags?workspace={gid}",
        opt_fields=["name", "created_at", "color", "notes", "workspace", "permalink_url", "resource_type"],
        partition_key="created_at",
    ),
    "sections": AsanaEndpointConfig(
        name="sections",
        fan_out="project",
        path_template="/projects/{gid}/sections",
        opt_fields=["name", "created_at", "project", "resource_type"],
        partition_key="created_at",
    ),
    "teams": AsanaEndpointConfig(
        name="teams",
        fan_out="organization",
        path_template="/organizations/{gid}/teams",
        opt_fields=["name", "description", "organization", "permalink_url", "visibility", "resource_type"],
    ),
    "custom_fields": AsanaEndpointConfig(
        name="custom_fields",
        fan_out="workspace",
        path_template="/workspaces/{gid}/custom_fields",
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
}

ENDPOINTS = tuple(ASANA_ENDPOINTS.keys())

# Asana exposes a server-side `modified_since` filter only on /tasks (and the premium-only
# task search endpoint). The other endpoints have no usable server-side timestamp filter, so
# the whole source ships full-refresh-only for now — declaring incremental support without a
# real server filter would make every "incremental" run cost the same as a full refresh.
# Incremental tasks (via `modified_since`) and the Events API are tracked as follow-ups; they
# need a live token to smoke-test the filter behaviour before we can rely on it.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
