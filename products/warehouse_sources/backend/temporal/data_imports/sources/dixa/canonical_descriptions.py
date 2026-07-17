"""Canonical, documentation-sourced descriptions for Dixa endpoints and columns.

Sourced from the official Dixa API reference (https://docs.dixa.io/) — both the main API
(dev.dixa.io/v1) and the Exports API (exports.dixa.io/v1). Keyed by the endpoint names in
`settings.py` `DIXA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Dixa table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "conversations": {
        "description": "A customer service conversation from the Dixa Exports API, with timing and handling metrics.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Conversation-Export/",
        "columns": {
            "id": "Unique identifier for the conversation.",
            "csid": "Conversation (case) sequence identifier shown in the Dixa UI.",
            "channel": "Channel the conversation came through (e.g. email, chat, phone).",
            "status": "Current status of the conversation (e.g. open, pending, closed).",
            "direction": "Direction of the conversation (inbound or outbound).",
            "subject": "Subject line of the conversation.",
            "queue_id": "Identifier of the queue the conversation was assigned to.",
            "assignee_id": "Identifier of the agent assigned to the conversation.",
            "requester_id": "Identifier of the end user who initiated the conversation.",
            "created_at": "Time at which the conversation was created, as a Unix timestamp (ms).",
            "updated_at": "Time at which the conversation was last updated, as a Unix timestamp (ms).",
            "closed_at": "Time at which the conversation was closed, as a Unix timestamp (ms).",
            "tags": "Tags applied to the conversation.",
        },
    },
    "agents": {
        "description": "An agent (team member) in the Dixa account.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Agents/",
        "columns": {
            "id": "Unique identifier for the agent.",
            "displayName": "Display name of the agent.",
            "email": "Email address of the agent.",
            "phoneNumber": "Phone number of the agent.",
            "roles": "Roles assigned to the agent.",
        },
    },
    "endusers": {
        "description": "An end user (customer) record in the Dixa account.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/End-Users/",
        "columns": {
            "id": "Unique identifier for the end user.",
            "displayName": "Display name of the end user.",
            "email": "Email address of the end user.",
            "phoneNumber": "Phone number of the end user.",
            "createdAt": "Time at which the end user was created.",
        },
    },
    "queues": {
        "description": "A queue that conversations are routed into for handling by agents.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Queues/",
        "columns": {
            "id": "Unique identifier for the queue.",
            "name": "Name of the queue.",
            "isDefault": "Whether this is the account's default queue.",
        },
    },
    "tags": {
        "description": "A tag that can be applied to conversations to categorize them.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Tags/",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
            "state": "State of the tag (e.g. active, deactivated).",
        },
    },
}
