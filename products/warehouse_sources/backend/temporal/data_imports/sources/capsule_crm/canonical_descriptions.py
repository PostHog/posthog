"""Canonical, documentation-sourced descriptions for Capsule CRM endpoints and columns.

Sourced from the official Capsule CRM API reference (https://developer.capsulecrm.com/v2/overview/introduction).
Keyed by the endpoint names in `settings.py` `CAPSULE_CRM_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Capsule table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "parties": {
        "description": "A person or organisation in your Capsule account (a contact). The `type` field distinguishes people from organisations.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Party",
        "columns": {
            "id": "Unique identifier for the party.",
            "type": "Whether the party is a 'person' or an 'organisation'.",
            "firstName": "First name (people only).",
            "lastName": "Last name (people only).",
            "title": "Honorific title such as Mr or Ms (people only).",
            "jobTitle": "The person's job title.",
            "name": "Organisation name (organisations only).",
            "about": "Free-text description of the party.",
            "organisation": "The organisation a person belongs to.",
            "owner": "The user who owns this party.",
            "team": "The team this party is assigned to.",
            "addresses": "Postal addresses associated with the party.",
            "phoneNumbers": "Phone numbers associated with the party.",
            "emailAddresses": "Email addresses associated with the party.",
            "websites": "Websites and social profiles associated with the party.",
            "tags": "Tags applied to the party (when embedded).",
            "fields": "Custom field values for the party (when embedded).",
            "pictureURL": "URL of the party's profile picture.",
            "lastContactedAt": "Time the party was last contacted.",
            "createdAt": "Time the party was created.",
            "updatedAt": "Time the party was last updated.",
        },
    },
    "opportunities": {
        "description": "A potential sale (deal) tracked in your sales pipeline, linked to a party.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Opportunity",
        "columns": {
            "id": "Unique identifier for the opportunity.",
            "name": "The opportunity's name.",
            "description": "Free-text description of the opportunity.",
            "party": "The party (contact) this opportunity is associated with.",
            "milestone": "The current pipeline milestone of the opportunity.",
            "pipeline": "The sales pipeline this opportunity belongs to.",
            "value": "The monetary value of the opportunity, with amount and currency.",
            "probability": "Estimated probability of winning, as a percentage.",
            "durationBasis": "The unit the duration is measured in (e.g. DAY, MONTH).",
            "duration": "The expected duration of the opportunity.",
            "owner": "The user who owns this opportunity.",
            "team": "The team this opportunity is assigned to.",
            "expectedCloseOn": "The date the opportunity is expected to close.",
            "closedOn": "The date the opportunity was closed.",
            "lostReason": "The reason the opportunity was lost, if applicable.",
            "tags": "Tags applied to the opportunity (when embedded).",
            "fields": "Custom field values for the opportunity (when embedded).",
            "lastContactedAt": "Time the opportunity's party was last contacted.",
            "createdAt": "Time the opportunity was created.",
            "updatedAt": "Time the opportunity was last updated.",
        },
    },
    "kases": {
        "description": "A project (historically called a case) used to organise ongoing work for a party.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Project",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "The project's name.",
            "description": "Free-text description of the project.",
            "status": "Whether the project is OPEN or CLOSED.",
            "party": "The party (contact) this project is associated with.",
            "owner": "The user who owns this project.",
            "team": "The team this project is assigned to.",
            "stage": "The current stage of the project.",
            "expectedCloseOn": "The date the project is expected to close.",
            "closedOn": "The date the project was closed.",
            "lastContactedAt": "Time the project's party was last contacted.",
            "tags": "Tags applied to the project (when embedded).",
            "fields": "Custom field values for the project (when embedded).",
            "createdAt": "Time the project was created.",
            "updatedAt": "Time the project was last updated.",
        },
    },
    "tasks": {
        "description": "A to-do item, optionally linked to a party, opportunity, or project.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Task",
        "columns": {
            "id": "Unique identifier for the task.",
            "description": "The task's title/description.",
            "detail": "Additional detail about the task.",
            "status": "The task status (e.g. OPEN, COMPLETED).",
            "category": "The category the task belongs to.",
            "party": "The party (contact) the task relates to.",
            "opportunity": "The opportunity the task relates to.",
            "kase": "The project the task relates to.",
            "owner": "The user the task is assigned to.",
            "dueOn": "The date the task is due.",
            "dueTime": "The time of day the task is due.",
            "completedAt": "Time the task was completed.",
            "createdAt": "Time the task was created.",
            "updatedAt": "Time the task was last updated.",
        },
    },
    "users": {
        "description": "A user of your Capsule account.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/User",
        "columns": {
            "id": "Unique identifier for the user.",
            "username": "The user's username.",
            "name": "The user's display name.",
            "status": "Whether the user is active.",
        },
    },
    "milestones": {
        "description": "A stage in a sales pipeline that opportunities progress through.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Milestone",
        "columns": {
            "id": "Unique identifier for the milestone.",
            "name": "The milestone's name.",
            "description": "Free-text description of the milestone.",
            "probability": "Default win probability associated with this milestone.",
            "complete": "Whether reaching this milestone marks the opportunity as won.",
        },
    },
    "pipelines": {
        "description": "A sales pipeline that groups a set of milestones.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Pipeline",
        "columns": {
            "id": "Unique identifier for the pipeline.",
            "name": "The pipeline's name.",
            "milestones": "The milestones that make up the pipeline.",
        },
    },
    "categories": {
        "description": "A category used to classify tasks.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/Category",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "The category's name.",
            "colour": "The display colour of the category.",
        },
    },
    "lost_reasons": {
        "description": "A predefined reason for marking an opportunity as lost.",
        "docs_url": "https://developer.capsulecrm.com/v2/operations/LostReason",
        "columns": {
            "id": "Unique identifier for the lost reason.",
            "name": "The lost reason's text.",
        },
    },
}
