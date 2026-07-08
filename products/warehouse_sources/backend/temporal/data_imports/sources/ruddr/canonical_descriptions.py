from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Ruddr API docs (https://docs.ruddr.io).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A client (customer company) tracked in your Ruddr workspace.",
        "docs_url": "https://docs.ruddr.io",
        "columns": {
            "id": "The unique ID of the client.",
            "key": "The short human-readable key of the client.",
            "name": "The client's name.",
            "code": "An optional external code for the client.",
            "currency": "The client's default currency.",
            "isInternal": "Whether the client represents internal (non-billable) work.",
            "createdAt": "When the client was created.",
        },
    },
    "projects": {
        "description": "A project delivered for a client in Ruddr.",
        "docs_url": "https://docs.ruddr.io",
        "columns": {
            "id": "The unique ID of the project.",
            "key": "The short human-readable key of the project.",
            "name": "The project's name.",
            "code": "An optional external code for the project.",
            "statusId": "The current status of the project.",
            "start": "The project's start date.",
            "end": "The project's end date.",
            "isBillable": "Whether time on the project is billable.",
            "currency": "The project's currency.",
            "fixedFee": "The fixed fee for the project, if any.",
        },
    },
    "project_tasks": {
        "description": "A task within a project in Ruddr.",
        "docs_url": "https://docs.ruddr.io",
        "columns": {
            "id": "The unique ID of the task.",
            "name": "The task's name.",
            "notes": "Free-text notes on the task.",
            "statusId": "The current status of the task.",
            "start": "The task's start date.",
            "end": "The task's end date.",
            "isBillable": "Whether time on the task is billable.",
            "budgetedHours": "The budgeted hours for the task.",
            "project": "The project the task belongs to.",
            "createdAt": "When the task was created.",
        },
    },
    "members": {
        "description": "A member (user) of your Ruddr workspace.",
        "docs_url": "https://docs.ruddr.io",
        "columns": {
            "id": "The unique ID of the member.",
            "name": "The member's full name.",
            "email": "The member's email address.",
            "isActive": "Whether the member is currently active.",
            "isBillable": "Whether the member's time is billable by default.",
            "employmentTypeId": "The member's employment type.",
            "defaultRate": "The member's default billing rate.",
            "defaultRateCurrency": "The currency of the member's default rate.",
            "activeStartDate": "When the member became active.",
            "activeEndDate": "When the member's active period ends.",
        },
    },
    "time_entries": {
        "description": "A time entry logged by a member against a project or task in Ruddr.",
        "docs_url": "https://docs.ruddr.io",
        "columns": {
            "id": "The unique ID of the time entry.",
            "date": "The date the time was logged for.",
            "minutes": "The number of minutes logged.",
            "notes": "Free-text notes on the time entry.",
            "typeId": "The type of the time entry.",
            "statusId": "The current status of the time entry.",
            "isBillable": "Whether the entry is billable.",
            "invoiced": "Whether the entry has been invoiced.",
            "member": "The member who logged the time.",
            "project": "The project the time was logged against.",
            "task": "The task the time was logged against.",
            "createdAt": "When the time entry was created.",
        },
    },
}
