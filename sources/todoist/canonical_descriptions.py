from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the official Todoist unified v1 API documentation (https://developer.todoist.com/api/v1).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tasks": {
        "description": "Active (non-completed) tasks in the user's Todoist account.",
        "docs_url": "https://developer.todoist.com/api/v1#tag/Tasks",
        "columns": {
            "id": "Unique identifier of the task.",
            "content": "The task's text content, supporting Markdown.",
            "description": "A longer description attached to the task.",
            "project_id": "ID of the project the task belongs to.",
            "section_id": "ID of the section the task belongs to, if any.",
            "parent_id": "ID of the parent task for sub-tasks, if any.",
            "priority": "Task priority from 1 (normal) to 4 (urgent).",
            "labels": "Names of the labels associated with the task.",
            "is_completed": "Whether the task has been completed.",
            "added_at": "Date and time the task was created.",
            "completed_at": "Date and time the task was completed, if it has been.",
            "updated_at": "Date and time the task was last updated.",
            "due": "Object describing the task's due date, if set.",
            "url": "URL to access the task in the Todoist web app.",
        },
    },
    "projects": {
        "description": "Projects (top-level task containers) in the user's Todoist account.",
        "docs_url": "https://developer.todoist.com/api/v1#tag/Projects",
        "columns": {
            "id": "Unique identifier of the project.",
            "name": "Name of the project.",
            "description": "Description of the project.",
            "color": "Color of the project icon.",
            "parent_id": "ID of the parent project for nested projects, if any.",
            "is_favorite": "Whether the project is marked as a favorite.",
            "is_inbox_project": "Whether the project is the user's Inbox.",
            "workspace_id": "ID of the workspace the project belongs to, if any.",
            "folder_id": "ID of the folder the project belongs to, if any.",
            "created_at": "Date and time the project was created.",
            "updated_at": "Date and time the project was last updated.",
            "url": "URL to access the project in the Todoist web app.",
        },
    },
    "sections": {
        "description": "Sections used to group tasks within a project.",
        "docs_url": "https://developer.todoist.com/api/v1#tag/Sections",
        "columns": {
            "id": "Unique identifier of the section.",
            "name": "Name of the section.",
            "project_id": "ID of the project the section belongs to.",
            "order": "Position of the section within the project.",
        },
    },
    "labels": {
        "description": "Personal labels that can be applied to tasks.",
        "docs_url": "https://developer.todoist.com/api/v1#tag/Labels",
        "columns": {
            "id": "Unique identifier of the label.",
            "name": "Name of the label.",
            "color": "Color of the label.",
            "order": "Position of the label in the label list.",
            "is_favorite": "Whether the label is marked as a favorite.",
        },
    },
    "collaborators": {
        "description": "Project<->collaborator membership: one row per (project, collaborator). The "
        "owning project_id is injected onto each collaborator row.",
        "docs_url": "https://developer.todoist.com/api/v1#tag/Projects",
        "columns": {
            "project_id": "ID of the project the collaborator has access to (injected by the connector).",
            "id": "Unique identifier of the collaborating user.",
            "name": "Full name of the collaborator.",
            "email": "Email address of the collaborator.",
        },
    },
}
