"""Canonical, documentation-sourced descriptions for HiBob (Bob) endpoints and columns.

Sourced from the official HiBob (Bob) API reference (https://apidocs.hibob.com/reference). Keyed by
the endpoint names in `settings.py` `HIBOB_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced HiBob table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "employees": {
        "description": "An employee record in Bob, including their personal, work, and employment details.",
        "docs_url": "https://apidocs.hibob.com/reference/post_people-search",
        "columns": {
            "id": "Unique identifier for the employee.",
            "firstName": "The employee's first name.",
            "surname": "The employee's surname (last name).",
            "displayName": "The employee's display name.",
            "email": "The employee's work email address.",
            "personal": "Personal details such as date of birth, nationality, and contact information.",
            "work": "Work details such as department, site, title, manager, and start date.",
            "about": "About details such as social links, hobbies, and food preferences.",
            "fullName": "The employee's full name.",
            "companyId": "Identifier of the company the employee belongs to.",
            "creationDate": "Date the employee record was created.",
            "humanReadable": "Whether reference and list values are flattened into readable strings.",
        },
    },
    "tasks": {
        "description": "A task assigned to employees in Bob, typically part of an onboarding or offboarding workflow.",
        "docs_url": "https://apidocs.hibob.com/reference/get_tasks",
        "columns": {
            "id": "Unique identifier for the task.",
            "employeeId": "Identifier of the employee the task is assigned to.",
            "name": "The task's name or title.",
            "description": "Description of what the task involves.",
            "status": "Current status of the task (e.g. open, completed).",
            "dueDate": "Date by which the task should be completed.",
            "completionDate": "Date the task was completed, if it has been.",
            "listId": "Identifier of the task list the task belongs to.",
            "listName": "Name of the task list the task belongs to.",
        },
    },
}
