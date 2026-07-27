"""Canonical, documentation-sourced descriptions for ClickUp endpoints and columns.

Sourced from the official ClickUp API reference (https://developer.clickup.com/reference). Keyed by
the endpoint names in `settings.py` `CLICKUP_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced ClickUp table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A ClickUp Workspace (Team) — the top-level container for spaces, members, and work.",
        "docs_url": "https://developer.clickup.com/reference/getauthorizedteams",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "The workspace's name.",
            "color": "The workspace's display color.",
            "avatar": "URL of the workspace's avatar image.",
            "members": "List of members belonging to the workspace.",
        },
    },
    "spaces": {
        "description": "A Space within a workspace, grouping folders and lists for a team or area of work.",
        "docs_url": "https://developer.clickup.com/reference/getspaces",
        "columns": {
            "id": "Unique identifier for the space.",
            "name": "The space's name.",
            "private": "Whether the space is private to its members.",
            "statuses": "The set of task statuses configured for the space.",
            "multiple_assignees": "Whether tasks in the space allow multiple assignees.",
            "archived": "Whether the space has been archived.",
        },
    },
    "folders": {
        "description": "A Folder within a space that groups related lists.",
        "docs_url": "https://developer.clickup.com/reference/getfolders",
        "columns": {
            "id": "Unique identifier for the folder.",
            "name": "The folder's name.",
            "orderindex": "Position of the folder within its space's ordering.",
            "statuses": "Task statuses configured for the folder when it overrides the space defaults.",
            "space": "The space the folder belongs to.",
            "task_count": "Number of tasks contained in the folder.",
            "lists": "Lists contained in the folder.",
            "hidden": "Whether the folder is hidden.",
            "archived": "Whether the folder has been archived.",
            "_space_id": "Identifier of the parent space, injected during the fan-out sync.",
        },
    },
    "lists": {
        "description": "A List of tasks, belonging either to a folder or directly to a space.",
        "docs_url": "https://developer.clickup.com/reference/getlists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "folder": "The folder the list belongs to, if any.",
            "space": "The space the list belongs to.",
            "task_count": "Number of tasks in the list.",
            "status": "The list's status configuration.",
            "due_date": "Due date set on the list, as a Unix timestamp in milliseconds.",
            "start_date": "Start date set on the list, as a Unix timestamp in milliseconds.",
            "archived": "Whether the list has been archived.",
        },
    },
    "tasks": {
        "description": "A task — a unit of work tracked in ClickUp with status, assignees, and dates.",
        "docs_url": "https://developer.clickup.com/reference/gettasks",
        "columns": {
            "id": "Unique identifier for the task.",
            "name": "The task's name.",
            "description": "The task's description.",
            "status": "The task's current status.",
            "date_created": "Time at which the task was created, as a Unix timestamp in milliseconds.",
            "date_updated": "Time at which the task was last updated, as a Unix timestamp in milliseconds.",
            "date_closed": "Time at which the task was closed, as a Unix timestamp in milliseconds.",
            "due_date": "Due date of the task, as a Unix timestamp in milliseconds.",
            "start_date": "Start date of the task, as a Unix timestamp in milliseconds.",
            "creator": "The user who created the task.",
            "assignees": "List of users assigned to the task.",
            "group_assignees": "User groups assigned to the task.",
            "top_level_parent": "Identifier of the top-level parent task, for subtasks.",
            "priority": "The task's priority level.",
            "list": "The list the task belongs to.",
            "folder": "The folder the task belongs to.",
            "space": "The space the task belongs to.",
            "tags": "Tags applied to the task.",
            "url": "URL of the task in the ClickUp app.",
        },
    },
    "goals": {
        "description": "A Goal — a measurable objective tracked in ClickUp, made up of targets.",
        "docs_url": "https://developer.clickup.com/reference/getgoals",
        "columns": {
            "id": "Unique identifier for the goal.",
            "name": "The goal's name.",
            "description": "The goal's description.",
            "owner": "The user who owns the goal.",
            "due_date": "Due date of the goal, as a Unix timestamp in milliseconds.",
            "start_date": "Start date of the goal, as a Unix timestamp in milliseconds.",
            "completed": "Whether the goal has been completed.",
            "percent_completed": "Completion progress of the goal, as a percentage.",
            "color": "The goal's display color.",
        },
    },
}
