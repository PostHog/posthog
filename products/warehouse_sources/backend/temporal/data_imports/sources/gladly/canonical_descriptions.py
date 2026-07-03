"""Canonical, documentation-sourced descriptions for Gladly endpoints and columns.

Sourced from the official Gladly Data Export / API reference (https://developer.gladly.com/). Keyed
by the endpoint names in `settings.py` `GLADLY_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Gladly table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "A customer profile in Gladly, with contact details and custom attributes.",
        "docs_url": "https://developer.gladly.com/rest/#tag/Customers",
        "columns": {
            "id": "Unique identifier for the customer.",
            "name": "The customer's name.",
            "emails": "Email addresses associated with the customer.",
            "phones": "Phone numbers associated with the customer.",
            "address": "Postal address of the customer.",
            "customAttributes": "Custom key-value attributes attached to the customer.",
            "externalCustomerId": "Identifier for the customer in your own system, if set.",
            "createdAt": "Time at which the customer profile was created.",
            "_job_updated_at": "updatedAt of the export job that produced this row (incremental cursor).",
        },
    },
    "conversation_items": {
        "description": "An item within a customer conversation — a message, call, chat, or status change.",
        "docs_url": "https://developer.gladly.com/rest/#tag/Conversations",
        "columns": {
            "id": "Unique identifier for the conversation item.",
            "conversationId": "Identifier of the conversation this item belongs to.",
            "customerId": "Identifier of the customer the conversation is with.",
            "content": "Payload of the item (the message, call, or event details).",
            "contentType": "Type of the item (e.g. message, chat, phone call, status change).",
            "initiator": "Who initiated the item (the customer or an agent).",
            "timestamp": "Time at which the item occurred.",
            "_job_updated_at": "updatedAt of the export job that produced this row (incremental cursor).",
        },
    },
    "agents": {
        "description": "An agent (staff user) in the Gladly workspace.",
        "docs_url": "https://developer.gladly.com/rest/#tag/Agents",
        "columns": {
            "id": "Unique identifier for the agent.",
            "name": "The agent's name.",
            "emailAddress": "The agent's email address.",
            "roles": "Roles assigned to the agent.",
            "disabled": "Whether the agent account is disabled.",
            "createdAt": "Time at which the agent was created.",
            "_job_updated_at": "updatedAt of the export job that produced this row (incremental cursor).",
        },
    },
    "topics": {
        "description": "A topic used to categorize and tag conversations in Gladly.",
        "docs_url": "https://developer.gladly.com/rest/#tag/Topics",
        "columns": {
            "id": "Unique identifier for the topic.",
            "name": "The topic's name.",
            "parentId": "Identifier of the parent topic, if this topic is nested.",
            "disabled": "Whether the topic is disabled.",
            "createdAt": "Time at which the topic was created.",
            "_job_updated_at": "updatedAt of the export job that produced this row (incremental cursor).",
        },
    },
}
