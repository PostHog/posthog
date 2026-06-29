from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are sourced from Clockify's public API docs (https://docs.clockify.me/). Partial
# coverage is fine — anything omitted falls back to LLM enrichment using the docs_url + data types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A Clockify workspace the API key's user belongs to. Workspaces are the top-level container for projects, clients, members, and time entries.",
        "docs_url": "https://docs.clockify.me/#tag/Workspace",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Display name of the workspace.",
            "hourlyRate": "Default hourly rate for the workspace (amount and currency).",
            "memberships": "The user's membership records within the workspace.",
            "workspaceSettings": "Workspace-level configuration (time rounding, defaults, feature toggles).",
        },
    },
    "users": {
        "description": "A member of a workspace. Each row is a user within one workspace (workspace_id + id is unique).",
        "docs_url": "https://docs.clockify.me/#tag/User",
        "columns": {
            "id": "Unique identifier for the user.",
            "workspace_id": "Identifier of the workspace this membership belongs to (added during sync).",
            "email": "User's email address.",
            "name": "User's display name.",
            "activeWorkspace": "Identifier of the user's currently active workspace.",
            "defaultWorkspace": "Identifier of the user's default workspace.",
            "status": "Account status within the workspace (e.g. ACTIVE, INACTIVE).",
        },
    },
    "clients": {
        "description": "A client within a workspace that projects can be billed to.",
        "docs_url": "https://docs.clockify.me/#tag/Client",
        "columns": {
            "id": "Unique identifier for the client.",
            "workspace_id": "Identifier of the workspace this client belongs to (added during sync).",
            "workspaceId": "Identifier of the workspace this client belongs to.",
            "name": "Client name.",
            "archived": "Whether the client is archived.",
        },
    },
    "projects": {
        "description": "A project within a workspace. Time entries and tasks are organized under projects.",
        "docs_url": "https://docs.clockify.me/#tag/Project",
        "columns": {
            "id": "Unique identifier for the project.",
            "workspace_id": "Identifier of the workspace this project belongs to (added during sync).",
            "workspaceId": "Identifier of the workspace this project belongs to.",
            "name": "Project name.",
            "clientId": "Identifier of the client the project is associated with, if any.",
            "billable": "Whether time logged to the project is billable by default.",
            "archived": "Whether the project is archived.",
            "color": "Display color of the project.",
            "duration": "Total tracked duration on the project (ISO 8601 duration).",
        },
    },
    "tags": {
        "description": "A tag within a workspace that can be attached to time entries for categorization.",
        "docs_url": "https://docs.clockify.me/#tag/Tag",
        "columns": {
            "id": "Unique identifier for the tag.",
            "workspace_id": "Identifier of the workspace this tag belongs to (added during sync).",
            "workspaceId": "Identifier of the workspace this tag belongs to.",
            "name": "Tag name.",
            "archived": "Whether the tag is archived.",
        },
    },
    "tasks": {
        "description": "A task belonging to a project. Each row is a task within one project (workspace_id + project_id + id is unique).",
        "docs_url": "https://docs.clockify.me/#tag/Task",
        "columns": {
            "id": "Unique identifier for the task.",
            "workspace_id": "Identifier of the workspace this task belongs to (added during sync).",
            "project_id": "Identifier of the project this task belongs to (added during sync).",
            "projectId": "Identifier of the project this task belongs to.",
            "name": "Task name.",
            "status": "Task status (e.g. ACTIVE, DONE).",
            "assigneeIds": "Identifiers of the users assigned to the task.",
            "duration": "Total tracked duration on the task (ISO 8601 duration).",
        },
    },
    "time_entries": {
        "description": "A logged time entry for a user. Each row is one entry for one user (workspace_id + user_id + id is unique). The nested timeInterval is flattened into time_interval_* columns.",
        "docs_url": "https://docs.clockify.me/#tag/Time-entry",
        "columns": {
            "id": "Unique identifier for the time entry.",
            "workspace_id": "Identifier of the workspace this entry belongs to (added during sync).",
            "user_id": "Identifier of the user who logged this entry (added during sync).",
            "userId": "Identifier of the user who logged this entry.",
            "workspaceId": "Identifier of the workspace this entry belongs to.",
            "projectId": "Identifier of the project the entry is logged against, if any.",
            "taskId": "Identifier of the task the entry is logged against, if any.",
            "description": "Free-text description of the work.",
            "billable": "Whether the entry is billable.",
            "tagIds": "Identifiers of the tags attached to the entry.",
            "time_interval_start": "Start timestamp of the entry (flattened from timeInterval.start). Used as the incremental cursor and partition key.",
            "time_interval_end": "End timestamp of the entry (flattened from timeInterval.end); null while the timer is running.",
            "time_interval_duration": "Duration of the entry as an ISO 8601 duration (flattened from timeInterval.duration).",
        },
    },
}
