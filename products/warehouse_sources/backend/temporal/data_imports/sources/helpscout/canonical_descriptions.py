"""Canonical, documentation-sourced descriptions for Help Scout endpoints and columns.

Sourced from the official Help Scout Mailbox API 2.0 reference
(https://developer.helpscout.com/mailbox-api/). Keyed by the endpoint names in `settings.py`
`HELP_SCOUT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Help Scout table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "conversations": {
        "description": "A single support conversation (email, chat, or phone) within a mailbox.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/conversations/list/",
        "columns": {
            "id": "Unique identifier for the conversation.",
            "number": "Conversation number, unique within the account and shown in the Help Scout UI.",
            "type": "Conversation type: email, chat, or phone.",
            "status": "Conversation status: active, pending, closed, or spam.",
            "state": "Conversation state: draft, published, or deleted.",
            "subject": "Conversation subject line.",
            "mailboxId": "ID of the mailbox the conversation belongs to.",
            "createdAt": "Time the conversation was created, in ISO 8601 format.",
            "closedAt": "Time the conversation was closed, in ISO 8601 format.",
            "userUpdatedAt": "Time a user last updated the conversation, in ISO 8601 format.",
        },
    },
    "threads": {
        "description": "A single message or note within a conversation.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/conversations/threads/list/",
        "columns": {
            "id": "Unique identifier for the thread, unique within its conversation.",
            "conversation_id": "ID of the conversation this thread belongs to.",
            "type": "Thread type, e.g. customer, message, note, or chat.",
            "status": "Thread status at the time it was created.",
            "state": "Thread state: draft, published, or deleted.",
            "body": "Thread body content.",
            "createdAt": "Time the thread was created, in ISO 8601 format.",
        },
    },
    "customers": {
        "description": "A customer who has contacted or been added to your Help Scout account.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/customers/list/",
        "columns": {
            "id": "Unique identifier for the customer.",
            "firstName": "Customer's first name.",
            "lastName": "Customer's last name.",
            "photoUrl": "URL of the customer's photo.",
            "createdAt": "Time the customer was created, in ISO 8601 format.",
            "modifiedAt": "Time the customer was last modified, in ISO 8601 format.",
        },
    },
    "mailboxes": {
        "description": "A Help Scout mailbox (inbox) that conversations are organized under.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/inboxes/list/",
        "columns": {
            "id": "Unique identifier for the mailbox.",
            "name": "Mailbox display name.",
            "slug": "URL-friendly identifier for the mailbox.",
            "email": "Email address associated with the mailbox.",
            "createdAt": "Time the mailbox was created, in ISO 8601 format.",
            "updatedAt": "Time the mailbox was last updated, in ISO 8601 format.",
        },
    },
    "users": {
        "description": "A Help Scout user (agent) who can be assigned conversations.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/users/list/",
        "columns": {
            "id": "Unique identifier for the user.",
            "firstName": "User's first name.",
            "lastName": "User's last name.",
            "email": "User's email address.",
            "role": "User's role, e.g. owner, admin, or user.",
            "type": "User type.",
            "createdAt": "Time the user was created, in ISO 8601 format.",
            "updatedAt": "Time the user was last updated, in ISO 8601 format.",
        },
    },
    "tags": {
        "description": "A tag used to categorize conversations across all mailboxes.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/tags/list/",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Tag display name as shown in the app.",
            "slug": "URL-friendly identifier for the tag.",
            "ticketCount": "Number of conversations tagged with this tag.",
            "createdAt": "Time the tag was created, in ISO 8601 format.",
        },
    },
    "workflows": {
        "description": "A manual or automatic workflow that runs actions on conversations.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/workflows/list/",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "mailboxId": "ID of the mailbox the workflow applies to.",
            "type": "Workflow type: manual or automatic.",
            "status": "Workflow status: active, inactive, or invalid.",
            "name": "Workflow display name.",
            "createdAt": "Time the workflow was created, in ISO 8601 format.",
            "modifiedAt": "Time the workflow was last modified, in ISO 8601 format.",
        },
    },
    "mailbox_fields": {
        "description": "A custom field defined on a mailbox (inbox), with its dropdown options.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/inboxes/inbox-fields/",
        "columns": {
            "id": "Unique identifier for the custom field.",
            "mailbox_id": "ID of the mailbox the custom field belongs to.",
            "name": "Name of the custom field, as seen in the Help Scout app.",
            "type": "Type of the custom field.",
            "required": "Whether the custom field must be set.",
            "order": "Display order of the custom field in the Help Scout app.",
            "options": "Dropdown options, each with an id, a display order, and a label.",
            "systemType": "System feature that owns the field (topic or sentiment). Absent for user-created fields.",
        },
    },
    "organizations": {
        "description": "A company that customers belong to.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/organizations/list/",
        "columns": {
            "id": "Unique identifier for the organization.",
            "name": "Organization name.",
            "website": "Organization website.",
            "description": "Organization description.",
            "location": "Organization location.",
            "logoUrl": "URL of the organization logo.",
            "note": "Free-text note about the organization.",
            "domains": "Email domains that belong to the organization.",
            "phones": "Phone numbers of the organization.",
            "brandColor": "Brand color of the organization, as a hex code.",
        },
    },
    "teams": {
        "description": "A team of users that conversations can be assigned to.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/teams/list-teams/",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Team name.",
            "initials": "Team initials.",
            "mention": "Handle used to @mention the team in a thread body.",
            "timezone": "Team timezone.",
            "photoUrl": "URL of the team photo, if one exists.",
            "createdAt": "Time the team was created, in ISO 8601 format.",
            "updatedAt": "Time the team was last modified, in ISO 8601 format.",
        },
    },
    "happiness_ratings": {
        "description": "A happiness rating a customer left on a reply in a conversation.",
        "docs_url": "https://developer.helpscout.com/mailbox-api/endpoints/reports/happiness/reports-happiness-ratings/",
        "columns": {
            "id": "ID of the rated conversation.",
            "number": "Number of the rated conversation.",
            "type": "Conversation type: email, chat, or phone.",
            "threadid": "ID of the rated thread.",
            "threadCreatedAt": "Time the conversation was created, in ISO 8601 format.",
            "ratingId": "Rating value: 1 is Great, 2 is OK, 3 is Not Good.",
            "ratingComments": "Comments the customer left with the rating, if any.",
            "ratingCreatedAt": "Time the rating was created, in ISO 8601 format.",
            "ratingCustomerId": "ID of the customer who left the rating.",
            "ratingCustomerName": "Name of the customer who left the rating.",
            "ratingUserId": "ID of the user the rating is for.",
            "ratingUserName": "Name of the user the rating is for.",
        },
    },
}
