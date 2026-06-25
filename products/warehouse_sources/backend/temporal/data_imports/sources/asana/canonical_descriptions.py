"""Canonical, documentation-sourced descriptions for Asana endpoints and columns.

Sourced from the official Asana API reference (https://developers.asana.com/reference/rest-api-reference).
Keyed by the endpoint names in `settings.py` `ASANA_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Asana table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Asana objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "gid": "Globally unique identifier for the resource.",
    "resource_type": "The base type of the resource (e.g. 'task', 'project', 'user').",
    "name": "Name of the resource.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A workspace or organization — the highest-level container for all Asana data.",
        "docs_url": "https://developers.asana.com/reference/workspaces",
        "columns": _columns(
            email_domains="Email domains that are associated with this workspace.",
            is_organization="Whether the workspace is an organization (as opposed to a plain workspace).",
        ),
    },
    "users": {
        "description": "A member of an Asana workspace or organization.",
        "docs_url": "https://developers.asana.com/reference/users",
        "columns": _columns(
            email="The user's email address.",
            photo="A map of the user's profile photo in various sizes.",
            workspaces="Workspaces and organizations the user is a member of.",
        ),
    },
    "projects": {
        "description": "A collection of tasks with a shared purpose, owner, and timeline.",
        "docs_url": "https://developers.asana.com/reference/projects",
        "columns": _columns(
            created_at="Time at which the project was created.",
            modified_at="Time at which the project was last modified.",
            archived="Whether the project is archived.",
            color="Color of the project in the Asana UI.",
            current_status="The most recently posted status update for the project.",
            default_view="The default layout used when viewing the project (list, board, calendar, timeline).",
            due_date="Date on which the project is due (deprecated in favor of due_on).",
            due_on="Date on which the project is due.",
            start_on="Date on which the project starts.",
            notes="Free-form textual notes describing the project.",
            public="Whether the project is public to its team.",
            owner="The user who owns the project.",
            team="The team that the project is shared with.",
            workspace="The workspace or organization the project is associated with.",
            completed="Whether the project is marked complete.",
            completed_at="Time at which the project was completed.",
            members="Users who are members of the project.",
            followers="Users following the project, who receive notifications about it.",
            permalink_url="URL linking to the project in the Asana UI.",
        ),
    },
    "tasks": {
        "description": "A unit of work in Asana — the basic object around which tasks are tracked.",
        "docs_url": "https://developers.asana.com/reference/tasks",
        "columns": _columns(
            created_at="Time at which the task was created.",
            modified_at="Time at which the task was last modified.",
            completed="Whether the task is currently marked complete.",
            completed_at="Time at which the task was completed.",
            due_on="Date on which the task is due.",
            due_at="Date and time on which the task is due, if a specific time was set.",
            start_on="Date on which the task starts.",
            assignee="The user to whom the task is assigned.",
            assignee_status="Scheduling status of the task for the assignee (today, upcoming, later).",
            notes="Free-form textual notes describing the task.",
            parent="The parent task, if this task is a subtask.",
            projects="Projects the task is associated with.",
            tags="Tags applied to the task.",
            workspace="The workspace or organization the task is associated with.",
            resource_subtype="The subtype of the task (e.g. 'default_task', 'milestone').",
            num_hearts="Number of users who have hearted the task.",
            num_likes="Number of users who have liked the task.",
            permalink_url="URL linking to the task in the Asana UI.",
            custom_fields="Values of custom fields applied to the task.",
        ),
    },
    "tags": {
        "description": "A label that can be applied to tasks to group and categorize them.",
        "docs_url": "https://developers.asana.com/reference/tags",
        "columns": _columns(
            created_at="Time at which the tag was created.",
            color="Color of the tag in the Asana UI.",
            notes="Free-form textual notes describing the tag.",
            workspace="The workspace or organization the tag is associated with.",
            permalink_url="URL linking to the tag in the Asana UI.",
        ),
    },
    "sections": {
        "description": "A grouping within a project that organizes its tasks.",
        "docs_url": "https://developers.asana.com/reference/sections",
        "columns": _columns(
            created_at="Time at which the section was created.",
            project="The project the section belongs to.",
        ),
    },
    "teams": {
        "description": "A group of users within an organization that share projects and conversations.",
        "docs_url": "https://developers.asana.com/reference/teams",
        "columns": _columns(
            description="Description of the team.",
            organization="The organization the team belongs to.",
            permalink_url="URL linking to the team in the Asana UI.",
            visibility="Visibility of the team (secret, request_to_join, or public).",
        ),
    },
    "custom_fields": {
        "description": "A custom field definition used to add structured metadata to tasks and projects.",
        "docs_url": "https://developers.asana.com/reference/custom-fields",
        "columns": _columns(
            description="Description of the custom field.",
            type="Type of the custom field (text, number, enum, multi_enum, date, people).",
            resource_subtype="The subtype of the custom field, matching its type.",
            enabled="Whether the custom field is enabled.",
            format="Format applied to the field's value (currency, percentage, duration, etc.).",
            precision="Number of decimal places shown for numeric fields.",
            is_global_to_workspace="Whether the custom field is available across the whole workspace.",
            created_by="The user who created the custom field.",
        ),
    },
}
