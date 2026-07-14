"""Canonical, documentation-sourced descriptions for Float endpoints and columns.

Sourced from the official Float API reference (https://developer.float.com/api_reference.html).
Keyed by the endpoint names in `settings.py` `FLOAT_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Float table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://developer.float.com/api_reference.html"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "people": {
        "description": "A person scheduled in Float — a team member or placeholder that work is allocated to.",
        "docs_url": _DOCS_URL,
        "columns": {
            "people_id": "Unique identifier for the person.",
            "name": "The person's full name.",
            "email": "The person's email address.",
            "job_title": "The person's job title.",
            "department": "The department the person belongs to.",
            "people_type_id": "Employment type: 1 = employee, 2 = contractor, 3 = placeholder.",
            "active": "Whether the person is active (1) or archived (0).",
            "start_date": "The person's start date.",
            "end_date": "The person's end date, if set.",
            "default_hourly_rate": "The person's default hourly rate.",
            "tags": "Tags applied to the person.",
            "created": "Time at which the person was created.",
            "modified": "Time at which the person was last modified.",
        },
    },
    "accounts": {
        "description": "A Float login account with its access level and role in the workspace.",
        "docs_url": _DOCS_URL,
        "columns": {
            "account_id": "Unique identifier for the account.",
            "name": "The account holder's name.",
            "email": "The account's email address.",
            "account_type": "Account role: 1 = account owner, 2 = admin, 3 = project manager, etc.",
            "access": "Bitmask describing the account's access rights.",
            "active": "Whether the account is active (1) or deactivated (0).",
            "created": "Time at which the account was created.",
            "modified": "Time at which the account was last modified.",
        },
    },
    "clients": {
        "description": "A client that projects can be associated with.",
        "docs_url": _DOCS_URL,
        "columns": {
            "client_id": "Unique identifier for the client.",
            "name": "The client's name.",
        },
    },
    "departments": {
        "description": "A department used to group people in Float.",
        "docs_url": _DOCS_URL,
        "columns": {
            "department_id": "Unique identifier for the department.",
            "name": "The department's name.",
            "parent_id": "The id of the parent department, if this is a sub-department.",
        },
    },
    "projects": {
        "description": "A project that work (tasks, phases, milestones) is scheduled against.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project_id": "Unique identifier for the project.",
            "name": "The project's name.",
            "client_id": "The id of the client the project belongs to.",
            "color": "The project's display color (hex).",
            "notes": "Free-text notes on the project.",
            "tags": "Tags applied to the project.",
            "budget_type": "The project's budget type (e.g. hours, fee, per-phase).",
            "budget_total": "The project's total budget.",
            "default_hourly_rate": "The project's default hourly rate.",
            "non_billable": "Whether the project is non-billable (1) or billable (0).",
            "tentative": "Whether the project is tentative (1) or confirmed (0).",
            "active": "Whether the project is active (1) or archived (0).",
            "created": "Time at which the project was created.",
            "modified": "Time at which the project was last modified.",
        },
    },
    "phases": {
        "description": "A phase within a project, bounding a date range with its own budget and rate.",
        "docs_url": _DOCS_URL,
        "columns": {
            "phase_id": "Unique identifier for the phase.",
            "project_id": "The id of the project the phase belongs to.",
            "name": "The phase's name.",
            "start_date": "The phase's start date.",
            "end_date": "The phase's end date.",
            "created": "Time at which the phase was created.",
            "modified": "Time at which the phase was last modified.",
        },
    },
    "tasks": {
        "description": "An allocation (scheduled task) assigning a person to work over a date range.",
        "docs_url": _DOCS_URL,
        "columns": {
            "task_id": "Unique identifier for the allocation.",
            "project_id": "The id of the project the allocation belongs to.",
            "phase_id": "The id of the phase the allocation belongs to, if any.",
            "people_id": "The id of the person assigned to the allocation.",
            "name": "The allocation's task name.",
            "start_date": "The allocation's start date.",
            "end_date": "The allocation's end date.",
            "hours": "Hours per day allocated.",
            "billable": "Whether the allocation is billable (1) or not (0).",
            "status": "The allocation's status: 1 = tentative, 2 = confirmed, 3 = complete.",
            "created": "Time at which the allocation was created.",
            "modified": "Time at which the allocation was last modified.",
        },
    },
    "project_tasks": {
        "description": "A named task defined on a project (the reusable task names allocations can use).",
        "docs_url": _DOCS_URL,
    },
    "milestones": {
        "description": "A milestone marking a key date on a project.",
        "docs_url": _DOCS_URL,
        "columns": {
            "milestone_id": "Unique identifier for the milestone.",
            "project_id": "The id of the project the milestone belongs to.",
            "name": "The milestone's name.",
            "date": "The milestone's start date.",
            "end_date": "The milestone's end date.",
        },
    },
    "timeoffs": {
        "description": "A time off entry for one or more people over a date range.",
        "docs_url": _DOCS_URL,
        "columns": {
            "timeoff_id": "Unique identifier for the time off entry.",
            "timeoff_type_id": "The id of the time off type.",
            "start_date": "The first day of the time off.",
            "end_date": "The last day of the time off.",
            "hours": "Hours per day of time off.",
            "full_day": "Whether the time off is a full day (1) or partial (0).",
            "people_ids": "The ids of the people the time off applies to.",
            "status": "Approval status of the time off.",
            "created": "Time at which the time off was created.",
            "modified": "Time at which the time off was last modified.",
        },
    },
    "timeoff_types": {
        "description": "A category of time off (e.g. vacation, sick leave) configured in the workspace.",
        "docs_url": _DOCS_URL,
        "columns": {
            "timeoff_type_id": "Unique identifier for the time off type.",
            "timeoff_type_name": "The name of the time off type.",
            "color": "The type's display color (hex).",
            "balance_type": "How the type's balance is tracked.",
            "days_per_year": "The number of days allotted per year for this type.",
        },
    },
    "logged_time": {
        "description": "An entry of actual hours logged against a project (and optionally a task) on a date.",
        "docs_url": _DOCS_URL,
        "columns": {
            "logged_time_id": "Unique identifier for the logged time entry.",
            "project_id": "The id of the project the time was logged against.",
            "phase_id": "The id of the phase the time was logged against, if any.",
            "people_id": "The id of the person who logged the time.",
            "task_id": "The id of the allocation the time was logged against, if any.",
            "date": "The date the time was logged for.",
            "hours": "The number of hours logged.",
            "billable": "Whether the logged time is billable (1) or not (0).",
            "note": "Free-text note on the logged time.",
            "created": "Time at which the logged time was created.",
            "modified": "Time at which the logged time was last modified.",
        },
    },
    "status": {
        "description": "A status entry marking a person as available/unavailable over a date range.",
        "docs_url": _DOCS_URL,
        "columns": {
            "status_id": "Unique identifier for the status entry.",
            "people_id": "The id of the person the status applies to.",
            "start_date": "The first day the status applies.",
            "end_date": "The last day the status applies.",
        },
    },
    "roles": {
        "description": "A role that can be assigned to people in the workspace.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the role.",
            "name": "The role's name.",
        },
    },
    "holidays": {
        "description": "A company-wide (public) holiday that blocks scheduling for everyone.",
        "docs_url": _DOCS_URL,
        "columns": {
            "holiday_id": "Unique identifier for the holiday.",
            "name": "The holiday's name.",
            "date": "The holiday's start date.",
            "end_date": "The holiday's end date.",
        },
    },
    "deleted_tasks": {
        "description": "Tombstone log of deleted allocations (tasks), for reconciling deletions since a cursor.",
        "docs_url": _DOCS_URL,
    },
    "deleted_timeoffs": {
        "description": "Tombstone log of deleted time off entries, for reconciling deletions since a cursor.",
        "docs_url": _DOCS_URL,
    },
    "deleted_logged_time": {
        "description": "Tombstone log of deleted logged-time entries, for reconciling deletions since a cursor.",
        "docs_url": _DOCS_URL,
    },
}
