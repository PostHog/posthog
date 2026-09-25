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
    "conversation_messages": {
        "description": "A single message exchanged in a conversation, fetched per synced conversation.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Messages/",
        "columns": {
            "id": "Unique identifier for the message.",
            "conversation_id": "Identifier of the conversation the message belongs to.",
            "conversation_updated_at": "Time at which the parent conversation was last updated, as a Unix timestamp (ms).",
            "authorId": "Identifier of the agent or end user who wrote the message.",
            "externalId": "Identifier the message carries in the originating system, when it has one.",
            "createdAt": "Time at which the message was created.",
            "attributes": "Channel-specific payload of the message, including its content, direction and attachments.",
        },
    },
    "conversation_ratings": {
        "description": "A satisfaction survey response or offer for a conversation. A survey with several questions returns one row per question, all sharing the same rating id.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Ratings/",
        "columns": {
            "id": "Identifier of the survey the rating belongs to. Shared by every question of the same survey.",
            "conversation_id": "Identifier of the conversation that was rated.",
            "conversation_updated_at": "Time at which the parent conversation was last updated, as a Unix timestamp (ms).",
            "ratingScore": "Score the end user gave, absent while the rating is only offered.",
            "ratingType": "Type of the rating question (Csat, Nps or ThumbsUpOrDown).",
            "ratingComment": "Free-text comment the end user left with the rating.",
            "conversationChannel": "Channel the rated conversation came through.",
            "agentId": "Identifier of the agent the rating is attributed to.",
            "userId": "Identifier of the end user the survey was sent to.",
            "ratingStatus": "Status of the rating (Unscheduled, Offered, Rated, Scheduled or Cancelled).",
            "language": "Language the survey was presented in.",
            "timestamps": "Times at which the rating was created, scheduled, offered and last modified.",
        },
    },
    "conversation_activity_log": {
        "description": "A state change on a conversation — assignment, status change, transfer, tagging — across the whole organization.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Conversations/",
        "columns": {
            "id": "Unique identifier for the activity log entry.",
            "conversationId": "Identifier of the conversation the activity happened on.",
            "activityTimestamp": "Time at which the activity happened.",
            "activityType": "Deprecated activity type name.",
            "_type": "Type of the activity, for example ConversationAssigned or ConversationClosed.",
            "author": "Agent or end user who caused the activity.",
            "attributes": "Activity-specific detail, for example the queue a conversation was transferred to.",
        },
    },
    "teams": {
        "description": "A team that agents are grouped into.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Teams/",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Name of the team.",
        },
    },
    "team_members": {
        "description": "Membership of an agent or admin in a team. One row per agent per team.",
        "docs_url": "https://docs.dixa.io/openapi/dixa-api/v1/tag/Teams/",
        "columns": {
            "team_id": "Identifier of the team the member belongs to.",
            "id": "Identifier of the agent or admin.",
            "name": "Name of the agent or admin.",
            "email": "Email address of the agent or admin.",
            "phoneNumber": "Phone number of the agent or admin.",
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
