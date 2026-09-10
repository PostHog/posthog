from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Huntr Organization API docs (https://docs.huntr.co).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment. Huntr timestamps are
# Unix seconds.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "members": {
        "description": "A member (job seeker) whose job search the organization is following in Huntr.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the member.",
            "firstName": "The member's first name.",
            "lastName": "The member's last name.",
            "email": "The member's email address.",
            "createdAt": "When the member was created (Unix seconds).",
        },
    },
    "advisors": {
        "description": "An advisor — an organization team member who manages and supports job seekers.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the advisor.",
            "firstName": "The advisor's first name.",
            "lastName": "The advisor's last name.",
            "email": "The advisor's email address.",
        },
    },
    "candidates": {
        "description": "A candidate profile managed within the organization.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the candidate.",
            "firstName": "The candidate's first name.",
            "lastName": "The candidate's last name.",
            "email": "The candidate's email address.",
        },
    },
    "jobs": {
        "description": "A job a member is tracking on their board (a saved role and its application progress).",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the job.",
            "title": "The job title.",
            "company": "The company the job is at.",
            "createdAt": "When the job was created (Unix seconds).",
        },
    },
    "job_posts": {
        "description": "A job post published or shared by the organization to its members.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the job post.",
            "title": "The job post title.",
            "createdAt": "When the job post was created (Unix seconds).",
        },
    },
    "employers": {
        "description": "An employer tracked by the organization.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the employer.",
            "name": "The employer's name.",
        },
    },
    "activities": {
        "description": "An activity — an interview, task, or event linked to a member's job search.",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the activity.",
            "createdAt": "When the activity was created (Unix seconds).",
        },
    },
    "actions": {
        "description": "An action recorded against a member or job (Huntr's successor to the deprecated events resource).",
        "docs_url": "https://docs.huntr.co",
        "columns": {
            "id": "The unique ID of the action.",
            "createdAt": "When the action was created (Unix seconds).",
        },
    },
}
