from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the official Hyperspell API reference (https://docs.hyperspell.com)
# and the published OpenAPI spec at https://api.hyperspell.com/openapi.json.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "memories": {
        "description": (
            "Every document indexed in the Hyperspell memory layer, across all connected sources "
            "(Slack, Notion, Google Drive, Gmail and more), with its indexing status and metadata."
        ),
        "docs_url": "https://docs.hyperspell.com/api-reference/memories/list-memories",
        "columns": {
            "resource_id": "Identifier of the document within its source; unique per source, not globally.",
            "source": "The provider the document was ingested from (e.g. slack, notion, google_drive, vault).",
            "type": "Hyperdoc document type discriminator (document, message, file, event, ...).",
            "title": "Human-readable document title.",
            "status": "Indexing status of the document (pending, processing, completed, failed, pending_review, skipped).",
            "collection": "The document's collection, if any.",
            "metadata": "Filterable custom metadata attached to the document.",
            "ingested_at": "When Hyperspell first indexed the document.",
            "last_modified_at": "When the source document was last modified.",
            "document_date": "The document's own date (e.g. email sent date, event date).",
            "document": "The full nested document payload (text, chunks, children).",
        },
    },
    "connections": {
        "description": "Data-source connections linked to the Hyperspell app or user (one per connected account).",
        "docs_url": "https://docs.hyperspell.com/api-reference/connections/list-connections",
        "columns": {
            "id": "Unique identifier for the connection.",
            "integration_id": "The integration this connection belongs to.",
            "provider": "The connection's provider (e.g. slack, notion, google_drive).",
            "label": "The connection's display label.",
            "selected_count": "Count of channels/workspaces selected for indexing on this connection.",
        },
    },
    "integrations": {
        "description": "The catalog of integrations available to the Hyperspell app, with their capabilities.",
        "docs_url": "https://docs.hyperspell.com/api-reference/integrations/list-all-integrations",
        "columns": {
            "id": "Unique identifier for the integration.",
            "provider": "The integration's provider.",
            "name": "The integration's display name.",
            "icon": "URL to the integration's icon.",
            "allow_multiple_connections": "Whether the integration allows multiple connections.",
            "auth_provider": "The integration's auth provider.",
            "actions_only": "Whether this integration only supports write actions (no sync).",
            "requires_channel_selection": "Whether the user must select channels before indexing starts.",
            "supports_channel_selection": "Whether the integration offers an optional channel picker to narrow indexing.",
            "channel_selection_required": "Whether an empty channel selection indexes nothing (the user must pick channels).",
        },
    },
    "entities": {
        "description": "Entities Hyperspell extracted from indexed documents (people, companies, topics, ...), app-wide.",
        "docs_url": "https://docs.hyperspell.com/api-reference/entities/list-entities",
        "columns": {
            "id": "Unique identifier for the entity.",
            "type": "The entity's type.",
            "name": "The entity's name.",
            "description": "A description of the entity, if available.",
            "attributes": "Structured attributes extracted for the entity.",
            "mention_count": "Number of documents mentioning the entity.",
            "first_seen_resource_id": "Resource id of the document the entity was first seen in.",
            "last_seen_resource_id": "Resource id of the document the entity was most recently seen in.",
            "created_at": "When the entity was first extracted.",
            "updated_at": "When the entity was last updated.",
        },
    },
    "queries": {
        "description": "The log of memory queries issued against the app, for evaluation and recall analysis.",
        "docs_url": "https://docs.hyperspell.com/api-reference/evaluation/list-prior-queries",
        "columns": {
            "query_id": "The ID of the query.",
            "user_id": "The ID of the user that issued the query, if any.",
            "time": "When the query was issued.",
            "query": "The query string that was issued.",
        },
    },
    "context_documents": {
        "description": "Context documents Hyperspell generated from the app's indexed data (summaries, digests, brains).",
        "docs_url": "https://docs.hyperspell.com/api-reference/context-documents/list-context-documents",
        "columns": {
            "document_id": "Unique identifier for the context document.",
            "status": "Generation status of the document.",
            "sources": "The source providers the document was generated from.",
            "model": "The model used to generate the document.",
            "created_at": "When generation was started.",
            "completed_at": "When generation completed, if it has.",
            "token_count": "Token count of the generated document.",
        },
    },
}
