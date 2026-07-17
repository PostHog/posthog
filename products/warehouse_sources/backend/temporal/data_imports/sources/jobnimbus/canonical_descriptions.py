from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the JobNimbus Open API docs (https://documenter.getpostman.com/view/3919598/S11PpG7g).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person or company in your JobNimbus CRM — a lead, customer, or business contact.",
        "docs_url": "https://documenter.getpostman.com/view/3919598/S11PpG7g",
        "columns": {
            "jnid": "The unique ID of the contact.",
            "display_name": "The contact's display name.",
            "first_name": "The contact's first name.",
            "last_name": "The contact's last name.",
            "company": "The company the contact is associated with.",
            "email": "The contact's primary email address.",
            "status_name": "The contact's current status in the workflow.",
            "record_type_name": "The contact record type.",
            "date_created": "When the contact was created (epoch seconds).",
            "date_updated": "When the contact was last updated (epoch seconds).",
        },
    },
    "jobs": {
        "description": "A job or project tracked in JobNimbus, typically linked to one or more contacts.",
        "docs_url": "https://documenter.getpostman.com/view/3919598/S11PpG7g",
        "columns": {
            "jnid": "The unique ID of the job.",
            "name": "The job name.",
            "number": "The human-readable job number.",
            "status_name": "The job's current status in the workflow.",
            "record_type_name": "The job record type.",
            "date_created": "When the job was created (epoch seconds).",
            "date_updated": "When the job was last updated (epoch seconds).",
            "date_status_change": "When the job status last changed (epoch seconds).",
        },
    },
    "tasks": {
        "description": "A to-do or scheduled task linked to a contact or job.",
        "docs_url": "https://documenter.getpostman.com/view/3919598/S11PpG7g",
        "columns": {
            "jnid": "The unique ID of the task.",
            "title": "The task title.",
            "description": "The task description.",
            "record_type_name": "The task record type.",
            "date_start": "When the task starts (epoch seconds).",
            "date_end": "When the task ends (epoch seconds).",
            "is_completed": "Whether the task has been completed.",
            "date_created": "When the task was created (epoch seconds).",
            "date_updated": "When the task was last updated (epoch seconds).",
        },
    },
    "activities": {
        "description": "An activity or note recorded against a contact or job (calls, emails, updates).",
        "docs_url": "https://documenter.getpostman.com/view/3919598/S11PpG7g",
        "columns": {
            "jnid": "The unique ID of the activity.",
            "note": "The activity note or message body.",
            "record_type_name": "The activity record type.",
            "primary": "The primary related record (contact or job) the activity is attached to.",
            "date_created": "When the activity was created (epoch seconds).",
            "date_updated": "When the activity was last updated (epoch seconds).",
        },
    },
}
