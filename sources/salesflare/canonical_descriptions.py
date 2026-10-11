from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Salesflare REST API docs (https://api.salesflare.com/docs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person in your Salesflare CRM — a lead, prospect, or customer contact.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the contact.",
            "email": "The contact's primary email address.",
            "name": "The contact's full name.",
            "firstname": "The contact's first name.",
            "lastname": "The contact's last name.",
            "phone_number": "The contact's phone number.",
            "creation_date": "When the contact was created.",
            "modification_date": "When the contact was last modified.",
        },
    },
    "accounts": {
        "description": "A company or organisation tracked in Salesflare.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the account.",
            "name": "The account (company) name.",
            "website": "The account's website URL.",
            "email": "The account's primary email address.",
            "creation_date": "When the account was created.",
            "modification_date": "When the account was last modified.",
        },
    },
    "opportunities": {
        "description": "A sales opportunity (deal) in a pipeline.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the opportunity.",
            "name": "The name of the opportunity.",
            "value": "The monetary value of the opportunity.",
            "pipeline": "The pipeline the opportunity belongs to.",
            "stage": "The current stage of the opportunity.",
            "close_date": "The expected or actual close date.",
            "creation_date": "When the opportunity was created.",
        },
    },
    "pipelines": {
        "description": "A sales pipeline that opportunities move through.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the pipeline.",
            "name": "The name of the pipeline.",
        },
    },
    "tasks": {
        "description": "A to-do or reminder linked to a contact, account, or opportunity.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the task.",
            "description": "The task description.",
            "reminder_date": "When the task is due.",
            "completed": "Whether the task has been completed.",
        },
    },
    "tags": {
        "description": "A label used to categorise contacts and accounts.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the tag.",
            "name": "The tag name.",
        },
    },
    "workflows": {
        "description": "An automated email workflow (campaign) configured in Salesflare.",
        "docs_url": "https://api.salesflare.com/docs",
        "columns": {
            "id": "The unique ID of the workflow.",
            "name": "The name of the workflow.",
        },
    },
}
