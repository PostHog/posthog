"""Canonical, documentation-sourced descriptions for Everhour endpoints and columns.

Sourced from the official Everhour API reference (https://everhour.docs.apiary.io/). Keyed by the
endpoint names in `settings.py` `EVERHOUR_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Everhour table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://everhour.docs.apiary.io/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A client (customer) in the Everhour account that projects can be associated with.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the client.",
            "name": "Name of the client.",
            "projects": "Project ids associated with this client.",
            "businessDetails": "Free-form billing/business details stored for the client.",
            "createdAt": "When the client was created.",
        },
    },
    "projects": {
        "description": "A project tracked in Everhour, including its budget settings and total tracked time.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the project. Integration projects are prefixed (e.g. 'as:' for Asana, 'tr:' for Trello).",
            "name": "Name of the project.",
            "type": "Project type (e.g. 'board') or the integration platform it originates from.",
            "workspaceId": "Identifier of the workspace the project belongs to.",
            "status": "Project status (e.g. 'open', 'archived').",
            "billing": "Billing configuration for the project (type and rate).",
            "budget": "Budget configuration for the project.",
            "client": "Identifier of the client the project belongs to, if any.",
            "createdAt": "When the project was created.",
        },
    },
    "users": {
        "description": "A member of the Everhour team.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "Display name of the user.",
            "email": "Email address of the user.",
            "role": "Role of the user within the team (e.g. 'admin', 'member').",
            "status": "Account status of the user (e.g. 'active', 'invited', 'removed').",
            "rate": "Configured billing/cost rate for the user.",
            "capacity": "Weekly work capacity configured for the user, in seconds.",
        },
    },
    "tasks": {
        "description": "A task within a project. Fanned out over every project, with the parent project id injected as `project_id`.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the task. Integration tasks are prefixed (e.g. 'as:' for Asana, 'jira:' for Jira).",
            "project_id": "Identifier of the parent project this task row was fetched under (injected by the connector).",
            "name": "Name of the task.",
            "type": "Task type (e.g. 'task').",
            "status": "Task status (e.g. 'open', 'completed').",
            "projects": "Project ids the task belongs to.",
            "time": "Tracked time totals for the task, in seconds.",
            "estimate": "Time estimate configured for the task.",
            "labels": "Labels/tags applied to the task.",
            "createdAt": "When the task was created.",
        },
    },
    "time_records": {
        "description": "Individual time entries logged against tasks. Supports incremental sync via the server-side from/to date window.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the time record.",
            "date": "Calendar date the time was logged for (YYYY-MM-DD).",
            "time": "Duration logged, in seconds.",
            "user": "The user who logged the time (nested object with id, name, avatar).",
            "task": "The task the time was logged against (nested object with id, name and its projects).",
            "comment": "Optional free-text comment on the time record.",
            "isLocked": "Whether the time record is locked from further edits.",
            "createdAt": "When the time record was created.",
        },
    },
}
