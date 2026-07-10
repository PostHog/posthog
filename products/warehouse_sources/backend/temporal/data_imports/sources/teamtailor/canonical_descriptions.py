from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Teamtailor public API docs (https://docs.teamtailor.com/).
# JSON:API resources nest their columns under `attributes`, plus a top-level `id` and `type`.
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "candidates": {
        "description": "A person in your Teamtailor account who has applied to or been sourced for a job.",
        "docs_url": "https://docs.teamtailor.com/",
        "columns": {
            "id": "The unique ID of the candidate.",
            "type": "The JSON:API resource type (always 'candidates').",
            "first-name": "The candidate's first name.",
            "last-name": "The candidate's last name.",
            "email": "The candidate's email address.",
            "phone": "The candidate's phone number.",
            "created-at": "When the candidate was created.",
            "updated-at": "When the candidate was last updated.",
            "sourced": "Whether the candidate was sourced rather than having applied.",
        },
    },
    "jobs": {
        "description": "A job posting (position) in your Teamtailor account.",
        "docs_url": "https://docs.teamtailor.com/",
        "columns": {
            "id": "The unique ID of the job.",
            "type": "The JSON:API resource type (always 'jobs').",
            "title": "The job title.",
            "status": "The current status of the job (e.g. open, archived).",
            "body": "The job description body.",
            "created-at": "When the job was created.",
            "updated-at": "When the job was last updated.",
            "start-date": "The job's start date.",
            "end-date": "The job's end date.",
        },
    },
    "job_applications": {
        "description": "An application linking a candidate to a job in Teamtailor.",
        "docs_url": "https://docs.teamtailor.com/",
        "columns": {
            "id": "The unique ID of the job application.",
            "type": "The JSON:API resource type (always 'job-applications').",
            "created-at": "When the application was created.",
            "updated-at": "When the application was last updated.",
            "sourced": "Whether the application came from a sourced candidate.",
            "rejected-at": "When the application was rejected, if applicable.",
        },
    },
    "users": {
        "description": "A user (recruiter or team member) in your Teamtailor account.",
        "docs_url": "https://docs.teamtailor.com/",
        "columns": {
            "id": "The unique ID of the user.",
            "type": "The JSON:API resource type (always 'users').",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "title": "The user's job title.",
            "role": "The user's role in Teamtailor.",
            "created-at": "When the user was created.",
            "updated-at": "When the user was last updated.",
        },
    },
    "departments": {
        "description": "A department used to organise jobs and users in Teamtailor.",
        "docs_url": "https://docs.teamtailor.com/",
        "columns": {
            "id": "The unique ID of the department.",
            "type": "The JSON:API resource type (always 'departments').",
            "name": "The department name.",
            "created-at": "When the department was created.",
            "updated-at": "When the department was last updated.",
        },
    },
}
