"""Canonical, documentation-sourced descriptions for Mem0 endpoints and columns.

Sourced from the official Mem0 API reference (https://docs.mem0.ai/api-reference).
Keyed by the endpoint names in `settings.py` `MEM0_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mem0 table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "memories": {
        "description": "A memory extracted and stored by Mem0 — a fact about a user, agent, app, or run.",
        "docs_url": "https://docs.mem0.ai/api-reference/memory/get-memories",
        "columns": {
            "id": "Unique identifier (UUID) for the memory.",
            "memory": "The extracted memory text.",
            "categories": "Categories assigned to the memory.",
            "metadata": "Custom metadata attached to the memory.",
            "created_at": "Time at which the memory was created.",
            "updated_at": "Time at which the memory was last updated.",
            "expiration_date": "Date after which the memory is considered expired.",
        },
    },
    "entities": {
        "description": "An entity (user, agent, app, or run) that owns memories in Mem0.",
        "docs_url": "https://docs.mem0.ai/api-reference/entities/get-users",
        "columns": {
            "id": "Unique identifier for the entity.",
            "name": "The entity's name.",
            "type": "The entity type: user, agent, app, or run.",
            "created_at": "Time at which the entity was created.",
            "updated_at": "Time at which the entity was last updated.",
            "total_memories": "Total number of memories associated with the entity.",
            "owner": "The entity's owner.",
            "organization": "The organization the entity belongs to.",
            "metadata": "Custom metadata attached to the entity.",
        },
    },
    "events": {
        "description": "A memory-operation event (add, search, etc) recorded by Mem0 for auditing and observability.",
        "docs_url": "https://docs.mem0.ai/api-reference/events/get-events",
        "columns": {
            "id": "Unique identifier (UUID) for the event.",
            "event_type": "The type of operation the event records (e.g. ADD, SEARCH).",
            "status": "Processing status of the event: PENDING, RUNNING, FAILED, or SUCCEEDED.",
            "payload": "The original payload submitted with the operation.",
            "metadata": "Extra metadata associated with the event.",
            "results": "Outputs produced by the operation.",
            "created_at": "Time at which the event was created.",
            "updated_at": "Time at which the event was last updated.",
            "started_at": "Time at which processing began.",
            "completed_at": "Time at which processing finished.",
            "latency": "Processing time in milliseconds.",
        },
    },
    "memory_history": {
        "description": "One change to a memory (add, update, or delete), with the memory text before and after.",
        "docs_url": "https://docs.mem0.ai/api-reference/memory/history-memory",
        "columns": {
            "id": "Unique identifier (UUID) for the history entry.",
            "memory_id": "Identifier of the memory this entry belongs to.",
            "input": "The conversation messages that led to this memory change.",
            "old_memory": "The memory text before the change, if any.",
            "new_memory": "The memory text after the change.",
            "event": "The type of change: ADD, UPDATE, or DELETE.",
            "user_id": "The user associated with the memory.",
            "agent_id": "The agent associated with the memory, if any.",
            "app_id": "The app associated with the memory, if any.",
            "session_id": "The run associated with the memory, if any.",
            "categories": "Categories of the memory at this point in its history.",
            "metadata": "Additional metadata attached to the change.",
            "created_at": "Time at which the history entry was created.",
            "updated_at": "Time at which the history entry was last updated.",
        },
    },
    "organizations": {
        "description": "A Mem0 organization that the API key's owner belongs to.",
        "docs_url": "https://docs.mem0.ai/api-reference/organization/get-orgs",
        "columns": {
            "org_id": "Unique identifier for the organization.",
            "name": "Name of the organization.",
            "members": "Members of the organization, with their roles.",
            "is_default": "Whether this is the caller's default organization.",
            "is_owner": "Whether the caller owns the organization.",
            "user_role": "The caller's role in the organization.",
            "created_at": "Time at which the organization was created.",
            "updated_at": "Time at which the organization was last updated.",
        },
    },
    "projects": {
        "description": "A Mem0 project, the scope that memories and events belong to.",
        "docs_url": "https://docs.mem0.ai/api-reference/project/get-projects",
        "columns": {
            "org_id": "Identifier of the organization the project belongs to.",
            "project_id": "Unique identifier for the project.",
            "name": "Name of the project.",
            "description": "Description of the project.",
            "members": "Members of the project, with their roles.",
            "custom_instructions": "Custom instructions for memory processing in the project.",
            "custom_categories": "Custom categories for memory categorization in the project.",
            "created_at": "Time at which the project was created.",
            "updated_at": "Time at which the project was last updated.",
        },
    },
}
