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
}
