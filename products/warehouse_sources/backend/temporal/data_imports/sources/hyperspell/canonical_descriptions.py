# Descriptions sourced from the Hyperspell OpenAPI spec (https://api.hyperspell.com/openapi.json)
# and API docs (https://docs.hyperspell.com/).
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "memories": {
        "description": "Documents indexed in Hyperspell's memory layer, ingested from connected sources (Slack, Notion, Gmail, Google Drive, and more) or added directly via the API.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "user_id": "The Hyperspell user the memory belongs to (empty when synced app-wide without a user).",
            "resource_id": "Identifier of the document within its source.",
            "source": "The provider the document was ingested from (e.g. slack, notion, google_drive, vault).",
            "type": "Document type discriminator (document, message, file, event, ...).",
            "title": "Human-readable document title.",
            "status": "Indexing status of the document (pending, processing, completed, failed, pending_review, skipped).",
            "collection": "The document's collection, if any.",
            "metadata": "Filterable custom metadata attached to the document.",
            "ingested_at": "When Hyperspell first indexed the document.",
            "last_modified_at": "When the source document was last modified.",
            "document_date": "The document's own date (e.g. email sent date, event date).",
        },
    },
    "connections": {
        "description": "Data-source connections users (or the app) have authorized, linking an integration like Slack or Google Drive to Hyperspell for indexing.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "user_id": "The Hyperspell user the connection belongs to (empty when synced app-wide without a user).",
            "id": "The connection's id.",
            "integration_id": "The connection's integration id.",
            "provider": "The connection's provider (e.g. slack, notion, google_drive).",
            "label": "The connection's label.",
            "selected_count": "Count of channels/workspaces selected for indexing on this connection.",
            "scope": "'user' for a personal connection; 'app' for an org-wide connection shared with every user of the app.",
        },
    },
    "integrations": {
        "description": "The catalog of integrations available to the app, with each integration's auth provider and selection requirements.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "id": "The integration's id.",
            "provider": "The integration's provider.",
            "name": "The integration's display name.",
            "icon": "URL to the integration's icon.",
            "allow_multiple_connections": "Whether the integration allows multiple connections.",
            "auth_provider": "The integration's auth provider.",
            "actions_only": "Whether this integration only supports write actions (no sync).",
            "requires_channel_selection": "Whether the user must select channels before indexing starts.",
            "supports_channel_selection": "Whether the integration offers an optional channel picker to narrow indexing.",
            "supports_folder_selection": "Whether the integration supports per-folder sync policies.",
        },
    },
    "vaults": {
        "description": "Vault collections of manually added documents, with the number of documents in each.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "user_id": "The Hyperspell user the vault belongs to (empty when synced app-wide without a user).",
            "collection": "The collection's name (empty string for the default vault).",
            "document_count": "Number of documents in the collection.",
        },
    },
    "entities": {
        "description": "Entities (people, companies, projects, ...) extracted from indexed memories, with mention counts and attributes.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "user_id": "The Hyperspell user the entity was extracted for (empty when synced app-wide without a user).",
            "id": "Unique identifier of the entity.",
            "type": "The entity's type.",
            "name": "The entity's name.",
            "description": "Description of the entity.",
            "attributes": "Structured attributes extracted for the entity.",
            "mention_count": "How many times the entity is mentioned across indexed documents.",
            "first_seen_resource_id": "Resource where the entity was first seen.",
            "last_seen_resource_id": "Resource where the entity was most recently seen.",
            "created_at": "When the entity was first extracted.",
            "updated_at": "When the entity was last updated.",
        },
    },
    "queries": {
        "description": "Prior queries issued against the app's memory index, useful for evaluating recall quality.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "query_id": "The ID of the query.",
            "user_id": "The ID of the user that issued the query, if any.",
            "time": "When the query was issued.",
            "query": "The query string that was issued.",
        },
    },
    "context_documents": {
        "description": "Context documents generated by Hyperspell for the app, summarizing indexed knowledge.",
        "docs_url": "https://docs.hyperspell.com/",
        "columns": {
            "document_id": "Unique identifier of the context document.",
            "status": "Generation status of the document.",
            "sources": "The sources the document was generated from.",
            "model": "The model used to generate the document.",
            "created_at": "When generation was requested.",
            "completed_at": "When generation completed.",
            "token_count": "Token count of the generated document.",
            "error": "Error message if generation failed.",
        },
    },
}
