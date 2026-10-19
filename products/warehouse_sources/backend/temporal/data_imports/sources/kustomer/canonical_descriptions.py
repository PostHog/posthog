"""Canonical, documentation-sourced descriptions for Kustomer endpoints and columns.

Sourced from the official Kustomer API reference (https://developer.kustomer.com/kustomer-api-docs).
Keyed by the endpoint names in `settings.py` `KUSTOMER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Kustomer table. Kustomer rows follow the JSON:API shape
(`id`, `type`, `attributes`, `relationships`); the columns below describe the fields nested under
`attributes`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by every Kustomer JSON:API resource; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "type": "JSON:API resource type of the object (e.g. 'customer', 'conversation').",
    "createdAt": "Time at which the object was created.",
    "updatedAt": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A person or company that interacts with your business — the central record in Kustomer.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/customers",
        "columns": _columns(
            name="The customer's display name.",
            displayName="The customer's formatted display name.",
            externalId="Your own external identifier for the customer, if set.",
            emails="The customer's email addresses.",
            phones="The customer's phone numbers.",
            locations="The customer's known locations.",
            tags="Tags applied to the customer.",
            sentiment="Sentiment information derived for the customer.",
            company="The company the customer is associated with, if any.",
            lastActivityAt="Time of the customer's most recent activity.",
            lastSeenAt="Time the customer was last seen.",
        ),
    },
    "conversations": {
        "description": "A thread of messages and activity between a customer and your support team.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/conversations",
        "columns": _columns(
            name="The conversation's subject or name.",
            status="Current status of the conversation (e.g. open, snoozed, done).",
            priority="Priority assigned to the conversation.",
            channels="Channels the conversation took place on (e.g. email, chat).",
            tags="Tags applied to the conversation.",
            assignedUsers="Users assigned to the conversation.",
            assignedTeams="Teams assigned to the conversation.",
            customer="The customer this conversation belongs to.",
            messageCount="Number of messages in the conversation.",
            satisfaction="Satisfaction rating left for the conversation, if any.",
            firstResponse="Information about the first response in the conversation.",
            lastActivityAt="Time of the conversation's most recent activity.",
        ),
    },
    "users": {
        "description": "A member of your Kustomer organization (an agent, admin, or other team member).",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/users",
        "columns": _columns(
            name="The user's full name.",
            displayName="The user's display name.",
            email="The user's email address.",
            roles="Roles granted to the user, controlling their permissions.",
            avatarUrl="URL of the user's avatar image.",
            lastActivityAt="Time of the user's most recent activity.",
            lastLoginAt="Time the user last logged in.",
        ),
    },
    "teams": {
        "description": "A group of users in Kustomer used for routing and assignment.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/teams",
        "columns": _columns(
            name="The team's name.",
            displayName="The team's display name.",
        ),
    },
    "tags": {
        "description": "A label that can be applied to customers, conversations, or messages to categorize them.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/tags",
        "columns": _columns(
            name="The tag's name.",
            color="The tag's color.",
            visibility="Where the tag can be applied (e.g. customer, conversation).",
        ),
    },
    "brands": {
        "description": "A brand identity in Kustomer, used to support multiple products or businesses from one org.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/brands",
        "columns": _columns(
            name="The brand's name.",
            displayName="The brand's display name.",
            email="The brand's support email address.",
            domains="Domains associated with the brand.",
        ),
    },
    "companies": {
        "description": "A company (business account) that customers can be associated with, used for account-level reporting.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getcompanies",
        "columns": _columns(
            name="The company's name.",
            externalId="Your own external identifier for the company, if set.",
            tags="Tags applied to the company.",
            modifiedAt="Time at which the company was last modified by a user.",
        ),
    },
    "sub_statuses": {
        "description": "A conversation sub-status, a finer-grained state nested under a conversation status.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getsubstatuses",
        "columns": _columns(
            label="The sub-status's display label.",
            description="Description of what the sub-status means.",
            parentStatus="The conversation status this sub-status belongs to (e.g. open, snoozed, done).",
            resourceType="Resource type the sub-status applies to (always 'conversation' for this table).",
            default="Whether this is the default sub-status for its parent status.",
        ),
    },
    "satisfaction_forms": {
        "description": "A satisfaction (CSAT) survey form, defining when and how customers are asked to rate a conversation.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getsatisfaction",
        "columns": _columns(
            name="The form's name.",
            formType="Type of survey form (e.g. csat).",
            enabled="Whether the form is currently sent to customers.",
            channel="Channel the survey is sent on (e.g. email, chat).",
            description="Description of the form.",
            delayTime="Delay before the survey is sent.",
            scale="Rating scale settings, such as the number of options and the low and high labels.",
            ratingPrompt="The rating question shown to the customer.",
            questions="Follow-up questions on the form.",
            criteria="Conditions a conversation must meet for the survey to be sent.",
        ),
    },
    "messages": {
        "description": "A single message sent or received in a conversation, on any channel.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getmessages",
        "columns": _columns(
            channel="Channel the message was sent on (e.g. email, chat, sms).",
            app="App or integration that delivered the message.",
            direction="Whether the message is inbound from the customer ('in') or outbound from your team ('out').",
            preview="Short plain-text preview of the message body.",
            size="Size of the message.",
            status="Delivery status of the message (e.g. received, sent).",
            meta="Channel-specific metadata, such as the email subject, sender and recipients.",
            sentiment="Sentiment information derived for the message.",
            externalId="Identifier of the message in the external channel, if any.",
            sentAt="Time at which the message was sent.",
        ),
    },
    "notes": {
        "description": "An internal note that an agent added to a conversation or customer. Customers do not see notes.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getnotesfororg",
        "columns": _columns(
            body="Text of the note.",
        ),
    },
    "queues": {
        "description": "A routing queue that holds conversations and other work until an agent is assigned.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getqueues",
        "columns": _columns(
            name="Internal name of the queue.",
            displayName="Display name of the queue.",
            description="Description of the queue.",
            priority="Priority of the queue relative to other queues.",
            itemSize="Capacity that one work item from this queue uses.",
            system="Whether Kustomer created the queue as a system queue.",
            modifiedAt="Time at which the queue was last modified.",
        ),
    },
    "work_items": {
        "description": "A unit of routed work, such as a conversation, that a queue assigns to an agent.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getworkitems",
        "columns": _columns(
            resourceType="Type of the routed resource (e.g. conversation).",
            status="Routing status of the work item (e.g. queued, assigned).",
            paused="Whether the work item is paused.",
            channel="Channel of the routed resource (e.g. email, chat, voice).",
            queuedCount="Number of times the work item entered a queue.",
            priority="Routing priority of the work item.",
            itemSize="Capacity that the work item uses.",
            resourceCreatedAt="Time at which the routed resource was created.",
            workItemNumber="Sequential number of the work item.",
            lastRevision="Details of the latest routing revision, such as when the agent accepted the item.",
            modifiedAt="Time at which the work item was last modified.",
        ),
    },
    "work_sessions": {
        "description": "An agent's routing session, from sign-in to sign-out, with capacity and time spent in each status.",
        "docs_url": "https://developer.kustomer.com/kustomer-api-docs/reference/getworksessions",
        "columns": _columns(
            routable="Whether routing can assign work to the agent.",
            statusType="Current status type of the agent (available, unavailable, busy or offline).",
            workItemCount="Number of work items assigned to the agent.",
            pausedWorkItemCount="Number of paused work items assigned to the agent.",
            signedInAt="Time at which the agent signed in.",
            capacity="Capacity limits and remaining capacity for each priority.",
            capacityRemaining="Remaining capacity of the agent.",
            totalCapacity="Total capacity of the agent.",
            handledItemCount="Number of work items the agent handled in the session.",
            handledConversationCount="Number of conversations the agent handled in the session.",
            totalAvailable="Time the agent spent available.",
            totalUnavailable="Time the agent spent unavailable.",
            totalTimeByStatus="Time the agent spent in each routing status, keyed by status id.",
        ),
    },
}
