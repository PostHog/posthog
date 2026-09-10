from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# tawk.to's full API reference is only provided after REST API access approval, so column
# coverage is limited to fields verified from public sources; everything else falls back to
# LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "properties": {
        "description": "A tawk.to property (site) on the account, the container for widgets, chats, tickets, and members.",
        "docs_url": "https://help.tawk.to/article/rest-api",
        "columns": {
            "propertyId": "Unique identifier of the property.",
            "name": "Display name of the property.",
        },
    },
    "chats": {
        "description": "A live-chat conversation on a property, including its message transcript.",
        "docs_url": "https://help.tawk.to/article/rest-api",
        "columns": {
            "id": "Unique identifier of the chat.",
            "propertyId": "Identifier of the property the chat belongs to.",
            "createdOn": "Timestamp when the chat was created.",
            "messages": "Ordered message transcript of the chat, including sender and message type.",
        },
    },
    "tickets": {
        "description": "A support ticket raised on a property, created from missed chats or the ticket form.",
        "docs_url": "https://help.tawk.to/article/rest-api",
        "columns": {
            "id": "Unique identifier of the ticket.",
            "propertyId": "Identifier of the property the ticket belongs to.",
        },
    },
    "members": {
        "description": "An agent who is a member of a property, with their role and status.",
        "docs_url": "https://help.tawk.to/article/rest-api",
        "columns": {
            "propertyId": "Identifier of the property the member belongs to.",
        },
    },
}
