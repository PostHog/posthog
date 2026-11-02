from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://docs.twenty.com/developers/extend/api"

# Curated, docs-sourced descriptions for Twenty's standard CRM objects. Columns not covered here
# fall back to LLM enrichment. Every object also carries `id` / `createdAt` / `updatedAt` /
# `deletedAt`, listed once per table below since Twenty applies them uniformly.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "An organization tracked in the CRM, with people, opportunities, and notes attached.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the company.",
            "name": "The company's name.",
            "domainName": "The company's primary website domain.",
            "employees": "Approximate number of employees.",
            "linkedinLink": "Link to the company's LinkedIn page.",
            "address": "The company's postal address.",
            "annualRevenue": "The company's annual revenue.",
            "createdAt": "When the company was created.",
            "updatedAt": "When the company was last updated.",
            "deletedAt": "When the company was soft-deleted, if it has been.",
        },
    },
    "people": {
        "description": "A person tracked in the CRM, optionally linked to a company.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the person.",
            "name": "The person's first and last name.",
            "emails": "The person's email addresses.",
            "phones": "The person's phone numbers.",
            "jobTitle": "The person's job title.",
            "companyId": "Identifier of the company this person belongs to, if any.",
            "linkedinLink": "Link to the person's LinkedIn profile.",
            "createdAt": "When the person was created.",
            "updatedAt": "When the person was last updated.",
            "deletedAt": "When the person was soft-deleted, if it has been.",
        },
    },
    "opportunities": {
        "description": "A sales opportunity (deal) tracked through a pipeline stage.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the opportunity.",
            "name": "The opportunity's name.",
            "amount": "The opportunity's monetary value.",
            "closeDate": "Expected or actual close date.",
            "stage": "Pipeline stage the opportunity is currently in.",
            "companyId": "Identifier of the company this opportunity belongs to, if any.",
            "pointOfContactId": "Identifier of the person who is the point of contact, if any.",
            "createdAt": "When the opportunity was created.",
            "updatedAt": "When the opportunity was last updated.",
            "deletedAt": "When the opportunity was soft-deleted, if it has been.",
        },
    },
    "notes": {
        "description": "A free-text note, optionally attached to companies, people, or opportunities.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the note.",
            "title": "The note's title.",
            "bodyV2": "The note's rich-text body.",
            "createdAt": "When the note was created.",
            "updatedAt": "When the note was last updated.",
            "deletedAt": "When the note was soft-deleted, if it has been.",
        },
    },
    "tasks": {
        "description": "A to-do item, optionally attached to companies, people, or opportunities.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the task.",
            "title": "The task's title.",
            "bodyV2": "The task's rich-text body.",
            "status": "The task's status (e.g. todo, in progress, done).",
            "dueAt": "When the task is due.",
            "assigneeId": "Identifier of the workspace member assigned to the task, if any.",
            "createdAt": "When the task was created.",
            "updatedAt": "When the task was last updated.",
            "deletedAt": "When the task was soft-deleted, if it has been.",
        },
    },
    "activities": {
        "description": "An entry on a record's timeline (Twenty's `timelineActivities` object) — the audit trail of events such as record creation, updates, and relationship changes.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the timeline activity.",
            "name": "The type of event that happened (e.g. record created, updated).",
            "happensAt": "When the event happened.",
            "linkedRecordId": "Identifier of the record the event happened on.",
            "linkedObjectMetadataId": "Identifier of the object type the linked record belongs to.",
            "workspaceMemberId": "Identifier of the workspace member who triggered the event, if any.",
            "createdAt": "When the timeline activity was created.",
            "updatedAt": "When the timeline activity was last updated.",
            "deletedAt": "When the timeline activity was soft-deleted, if it has been.",
        },
    },
}
