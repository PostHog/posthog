"""Canonical, documentation-sourced descriptions for Lever endpoints and columns.

Sourced from the official Lever Data API reference (https://hire.lever.co/developer/documentation).
Keyed by the endpoint names in `settings.py` `LEVER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Lever table. Lever returns timestamps as epoch-millisecond
integers (normalized to epoch seconds during sync). Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "opportunities": {
        "description": "A candidate's pipeline for a specific role — Lever's central record tying a person to an opening.",
        "docs_url": "https://hire.lever.co/developer/documentation#opportunities",
        "columns": {
            "id": "Unique identifier for the opportunity.",
            "name": "The candidate's name.",
            "headline": "The candidate's headline (e.g. companies they've worked at).",
            "contact": "ID of the contact (person) this opportunity belongs to.",
            "emails": "The candidate's email addresses.",
            "phones": "The candidate's phone numbers.",
            "stage": "ID of the pipeline stage the opportunity is currently in.",
            "owner": "ID of the user who owns the opportunity.",
            "followers": "IDs of users following the opportunity.",
            "sources": "Sources the candidate came from.",
            "origin": "How the opportunity was added (e.g. applied, sourced, referred).",
            "tags": "Tags applied to the opportunity.",
            "applications": "IDs of applications associated with the opportunity.",
            "archived": "Archive information, including reason and date, if archived.",
            "createdAt": "Time the opportunity was created, as an epoch-millisecond timestamp.",
            "updatedAt": "Time the opportunity was last updated, as an epoch-millisecond timestamp.",
            "lastInteractionAt": "Time of the most recent interaction on the opportunity.",
        },
    },
    "postings": {
        "description": "A job posting (opening) in Lever that candidates can apply to.",
        "docs_url": "https://hire.lever.co/developer/documentation#postings",
        "columns": {
            "id": "Unique identifier for the posting.",
            "text": "The posting's title.",
            "state": "Current state of the posting (e.g. published, internal, closed, draft).",
            "user": "ID of the user who owns the posting.",
            "owner": "ID of the posting owner.",
            "hiringManager": "ID of the hiring manager for the posting.",
            "categories": "Categorization of the posting (team, department, location, commitment).",
            "tags": "Tags applied to the posting.",
            "urls": "URLs for the posting (e.g. the public apply page).",
            "createdAt": "Time the posting was created, as an epoch-millisecond timestamp.",
            "updatedAt": "Time the posting was last updated, as an epoch-millisecond timestamp.",
        },
    },
    "users": {
        "description": "A Lever user — a member of your hiring team.",
        "docs_url": "https://hire.lever.co/developer/documentation#users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "accessRole": "The user's access role (e.g. admin, team member, interviewer).",
            "deactivatedAt": "Time the user was deactivated, if applicable.",
            "createdAt": "Time the user was created, as an epoch-millisecond timestamp.",
        },
    },
    "requisitions": {
        "description": "A requisition tracking approved headcount for a role in Lever.",
        "docs_url": "https://hire.lever.co/developer/documentation#requisitions",
        "columns": {
            "id": "Unique identifier for the requisition.",
            "requisitionCode": "Your own code identifying the requisition.",
            "name": "The requisition's name.",
            "status": "Current status of the requisition (e.g. open, closed, on hold).",
            "headcountTotal": "Total approved headcount for the requisition.",
            "headcountHired": "Number of candidates hired against the requisition.",
            "owner": "ID of the user who owns the requisition.",
            "hiringManager": "ID of the hiring manager for the requisition.",
            "createdAt": "Time the requisition was created, as an epoch-millisecond timestamp.",
            "updatedAt": "Time the requisition was last updated, as an epoch-millisecond timestamp.",
        },
    },
    "archive_reasons": {
        "description": "A reason a candidate's opportunity can be archived (e.g. hired, rejected).",
        "docs_url": "https://hire.lever.co/developer/documentation#archive-reasons",
        "columns": {
            "id": "Unique identifier for the archive reason.",
            "text": "The archive reason's display text.",
            "status": "Whether the archive reason represents a hired or non-hired outcome.",
        },
    },
    "stages": {
        "description": "A stage in the Lever hiring pipeline that opportunities move through.",
        "docs_url": "https://hire.lever.co/developer/documentation#stages",
        "columns": {
            "id": "Unique identifier for the stage.",
            "text": "The stage's display name.",
        },
    },
    "sources": {
        "description": "A source through which candidates are added to Lever, keyed by its unique text value.",
        "docs_url": "https://hire.lever.co/developer/documentation#sources",
        "columns": {
            "text": "The source's name (also its unique identifier).",
            "count": "Number of candidates attributed to this source.",
        },
    },
    "tags": {
        "description": "A tag that can be applied to opportunities, keyed by its unique text value.",
        "docs_url": "https://hire.lever.co/developer/documentation#tags",
        "columns": {
            "text": "The tag's text (also its unique identifier).",
            "count": "Number of opportunities the tag is applied to.",
        },
    },
}
