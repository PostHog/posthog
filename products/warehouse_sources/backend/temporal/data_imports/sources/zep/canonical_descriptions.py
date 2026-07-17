from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "An individual interacting with your application. Each user owns a set of threads and a user-level knowledge graph.",
        "docs_url": "https://help.getzep.com/users",
        "columns": {
            "uuid": "Zep-assigned unique identifier for the user.",
            "user_id": "Your identifier for the user (any string, e.g. a username, email, or UUID).",
            "email": "Email address of the user.",
            "first_name": "First name of the user.",
            "last_name": "Last name of the user.",
            "metadata": "Arbitrary metadata associated with the user (deprecated).",
            "project_uuid": "Identifier of the Zep project the user belongs to.",
            "created_at": "Timestamp when the user was created.",
            "updated_at": "Timestamp when the user was last updated (deprecated).",
            "deleted_at": "Timestamp when the user was deleted, if applicable.",
            "session_count": "Number of sessions for the user (deprecated).",
            "disable_default_ontology": "Whether the default entity/edge ontology is disabled for this user's graph.",
        },
    },
    "threads": {
        "description": "A conversation belonging to a user. Each thread is a sequence of chat messages ingested into the user's knowledge graph.",
        "docs_url": "https://help.getzep.com/threads",
        "columns": {
            "uuid": "Zep-assigned unique identifier for the thread.",
            "thread_id": "Your identifier for the thread.",
            "user_id": "Identifier of the user the thread belongs to.",
            "project_uuid": "Identifier of the Zep project the thread belongs to.",
            "created_at": "Timestamp when the thread was created.",
        },
    },
    "thread_messages": {
        "description": "Chat messages within each thread. One row per message, enriched with its parent thread_id.",
        "docs_url": "https://help.getzep.com/sdk-reference/thread/get-messages-of-a-thread",
        "columns": {
            "uuid": "Unique identifier of the message.",
            "content": "The text content of the message.",
            "role": "Role of the message sender (e.g. user, assistant, system, tool).",
            "name": "Customizable name of the sender (e.g. 'john', 'sales_agent').",
            "processed": "Whether the message has been processed into the knowledge graph.",
            "metadata": "Arbitrary metadata associated with the message.",
            "created_at": "Timestamp when the message was created.",
            "thread_id": "Identifier of the thread this message belongs to.",
            "user_id": "Identifier of the user this thread's messages belong to.",
        },
    },
}
