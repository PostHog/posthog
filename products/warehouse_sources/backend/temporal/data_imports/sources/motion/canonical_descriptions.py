from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A Motion workspace, the container that holds a team's projects, tasks, and statuses.",
        "docs_url": "https://docs.usemotion.com/api-reference/workspaces/list",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Workspace name.",
            "teamId": "ID of the team the workspace belongs to.",
            "type": "Whether the workspace is individual or shared with a team.",
            "labels": "Labels available to tasks in this workspace.",
            "statuses": "Task statuses configured for this workspace.",
        },
    },
    "users": {
        "description": "A person with access to one of the workspaces this API key can read.",
        "docs_url": "https://docs.usemotion.com/api-reference/users/list",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's display name.",
            "email": "The user's email address.",
        },
    },
    "projects": {
        "description": "A project in a Motion workspace, grouping related tasks.",
        "docs_url": "https://docs.usemotion.com/api-reference/projects/list",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Project name.",
            "description": "Project description.",
            "workspaceId": "ID of the workspace the project belongs to.",
            "status": "Current project status, with whether that status counts as resolved.",
            "createdTime": "Date and time the project was created.",
            "updatedTime": "Date and time the project was last updated.",
            "customFieldValues": "Values of the custom fields defined on the project.",
        },
    },
    "tasks": {
        "description": "A task in a Motion workspace, including tasks Motion has auto-scheduled.",
        "docs_url": "https://docs.usemotion.com/api-reference/tasks/list",
        "columns": {
            "id": "Unique identifier for the task.",
            "name": "Task name.",
            "description": "Task description.",
            "completed": "Whether the task is complete.",
            "dueDate": "Date and time the task is due.",
            "duration": "Expected time the task takes, in minutes, or a marker such as REMINDER.",
            "priority": "Task priority, such as ASAP, HIGH, MEDIUM, or LOW.",
            "status": "Current task status, with whether that status counts as resolved.",
            "assignees": "Users the task is assigned to.",
            "workspace": "Workspace the task belongs to.",
            "project": "Project the task belongs to, when it has one.",
            "labels": "Labels applied to the task.",
            "scheduledStart": "Start of the block Motion scheduled for the task.",
            "scheduledEnd": "End of the block Motion scheduled for the task.",
            "customFieldValues": "Values of the custom fields defined on the task.",
        },
    },
}
