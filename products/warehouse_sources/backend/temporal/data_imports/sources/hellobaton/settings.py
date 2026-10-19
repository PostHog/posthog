from dataclasses import dataclass, field
from typing import Optional

# Baton's DRF PageNumberPagination defaults to and caps page size at 100. Always request the max
# to minimise round trips; the server ignores unknown params so this is safe even if it changes.
PER_PAGE = 100


@dataclass
class HellobatonEndpointConfig:
    name: str
    path: str  # Path under /api, with the trailing slash Baton's router requires (a 301 otherwise)
    # Stable creation-time field to partition by. None when the resource exposes no reliably
    # non-null created_at style field (partitioning on a nullable field rewrites partitions).
    partition_key: Optional[str] = "created"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# Baton exposes no server-side `updated_since`/`modified_after` filter and the tap-hellobaton Singer
# tap and Airbyte connector both ship full-refresh only, so every endpoint is full refresh here.
HELLOBATON_ENDPOINTS: dict[str, HellobatonEndpointConfig] = {
    "activity": HellobatonEndpointConfig(name="activity", path="/activity/"),
    "comments": HellobatonEndpointConfig(name="comments", path="/comments/"),
    "companies": HellobatonEndpointConfig(name="companies", path="/companies/"),
    "custom_fields": HellobatonEndpointConfig(name="custom_fields", path="/custom_fields/"),
    "custom_field_options": HellobatonEndpointConfig(name="custom_field_options", path="/custom_field_options/"),
    "custom_field_values": HellobatonEndpointConfig(name="custom_field_values", path="/custom_field_values/"),
    "departments": HellobatonEndpointConfig(name="departments", path="/departments/"),
    "milestones": HellobatonEndpointConfig(name="milestones", path="/milestones/"),
    "phases": HellobatonEndpointConfig(name="phases", path="/phases/"),
    "projects": HellobatonEndpointConfig(name="projects", path="/projects/"),
    "project_attachments": HellobatonEndpointConfig(name="project_attachments", path="/project_attachments/"),
    # Project phases carry no created/modified timestamp, and their start/end datetimes are nullable.
    "project_phases": HellobatonEndpointConfig(name="project_phases", path="/project_phases/", partition_key=None),
    "project_users": HellobatonEndpointConfig(name="project_users", path="/project_users/"),
    "tasks": HellobatonEndpointConfig(name="tasks", path="/tasks/"),
    "task_attachments": HellobatonEndpointConfig(name="task_attachments", path="/task_attachments/"),
    # Task deliverables carry no timestamp at all.
    "task_deliverables": HellobatonEndpointConfig(
        name="task_deliverables", path="/task_deliverables/", partition_key=None
    ),
    # Templates carry no non-null created/modified timestamp, so there's no stable partition key.
    "templates": HellobatonEndpointConfig(name="templates", path="/templates/", partition_key=None),
    # Time entries have no `created` field; `reference_date` is the stable non-null date they cover.
    "time_entries": HellobatonEndpointConfig(
        name="time_entries", path="/time_entries/", partition_key="reference_date"
    ),
    "users": HellobatonEndpointConfig(name="users", path="/users/"),
}

ENDPOINTS = tuple(HELLOBATON_ENDPOINTS.keys())
