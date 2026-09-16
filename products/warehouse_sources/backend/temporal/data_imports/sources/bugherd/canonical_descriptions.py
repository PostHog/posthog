from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS_URL = "https://docs.bugherd.com/api"

# The archived and feedback task lists return the same Task object as the board list.
_TASK_COLUMNS = {
    "id": "Globally unique task ID.",
    "local_task_id": "Project-scoped task number, shown as #number in the BugHerd UI.",
    "project_id": "ID of the project the task belongs to.",
    "created_at": "Timestamp when the task was created.",
    "updated_at": "Timestamp when the task was last updated.",
    "closed_at": "Timestamp when the task was closed, if applicable.",
    "deleted_at": "Timestamp when the task was deleted, if applicable.",
    "title": "The task's title.",
    "description": "The task's description.",
    "status": "Status column name the task is in (e.g. backlog, todo, doing, done, closed, or a custom column name).",
    "status_id": "Numeric status/column ID. 0=backlog, 1=todo, 2=doing, 4=done, 5=closed; values above 5 indicate a custom column.",
    "priority": "Priority label (not set, critical, important, normal, minor).",
    "priority_id": "Numeric priority ID corresponding to `priority`.",
    "site": "The website the task was logged on.",
    "url": "The specific page path the task was logged on.",
    "tag_names": "Tags applied to the task.",
    "external_id": "Optional external reference ID set via the API (e.g. a linked issue key).",
    "requester_email": "Email address of the person who reported the task.",
    "requester_id": "User ID of the person who reported the task, if they are a known user.",
    "assigned_to_id": "User ID the task is assigned to, if any.",
    "assignee_ids": "User IDs assigned to the task.",
    "due_at": "Timestamp the task is due, if set.",
    "column_id": "ID of the kanban column the task currently sits in.",
    "secret_link": "Unguessable public URL for the task; no login required.",
    "admin_link": "Task board URL for the task; login required.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Organization": {
        "description": "Top-level details about your BugHerd organization.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the organization.",
            "name": "The organization's display name.",
        },
    },
    "Users": {
        "description": "Team members and guests who belong to your BugHerd organization.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "The user's email address.",
            "display_name": "The user's display name.",
            "avatar_url": "URL of the user's avatar image.",
        },
    },
    "Projects": {
        "description": "Websites/projects tracked for visual feedback and bug reporting in BugHerd.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "The project's display name.",
            "created_at": "Timestamp when the project was created.",
            "devurl": "Primary website URL for the project.",
            "is_active": "Whether the project is active.",
            "is_public": "Whether public feedback is enabled on the project.",
            "has_custom_columns": "Whether the project has custom kanban columns beyond the defaults.",
            "guests_see_guests": "Whether guests can see other guests' feedback.",
            "owner_name": "The name of the project's owner.",
            "sites": "The website URLs associated with the project.",
            "api_key": "The project-scoped API key used by the BugHerd feedback widget.",
            "allow_guests_change_task_status": "Whether guests are permitted to change a task's status.",
            "assign_guests": "Whether guests can be assigned to tasks.",
        },
    },
    "Tasks": {
        "description": "Bug reports and feedback items ('tasks') logged against a project's kanban board.",
        "docs_url": _API_DOCS_URL,
        "columns": _TASK_COLUMNS,
    },
    "ArchivedTasks": {
        "description": "Tasks that have been closed or archived in a project, and so no longer appear on the active taskboard.",
        "docs_url": _API_DOCS_URL,
        "columns": _TASK_COLUMNS,
    },
    "FeedbackTasks": {
        "description": "Tasks sitting in a project's backlog (feedback) column, not yet triaged onto the board.",
        "docs_url": _API_DOCS_URL,
        "columns": _TASK_COLUMNS,
    },
    "Columns": {
        "description": "Kanban columns on a project's board, including the built-in backlog, todo, doing and done columns and any custom ones.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Identifier for the column, unique within its project.",
            "name": "The column's display name.",
            "project_id": "ID of the project the column belongs to.",
            "position": "Display order of the column on the board, 0-indexed.",
            "tasks_count": "Number of tasks in the column. BugHerd documents this as unreliable -- it can return incorrect or negative values.",
            "created_at": "Timestamp when the column was created.",
            "updated_at": "Timestamp when the column was last updated.",
        },
    },
    "TaskComments": {
        "description": "Comments posted on a task, forming its discussion thread.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Identifier for the comment, unique within its task.",
            "task_id": "ID of the task the comment was posted on.",
            "project_id": "ID of the project the commented-on task belongs to.",
            "text": "Body of the comment.",
            "created_at": "Timestamp when the comment was posted.",
            "user_id": "ID of the user who posted the comment.",
            "is_private": "Whether the comment is visible only to team members, not guests/clients.",
        },
    },
}
