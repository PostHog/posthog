from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Svix API docs (https://api.svix.com/docs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "applications": {
        "description": "A Svix application — an isolated tenant that owns its own endpoints and receives webhook messages.",
        "docs_url": "https://api.svix.com/docs",
        "columns": {
            "id": "The unique Svix-generated ID of the application.",
            "uid": "Your optional custom unique identifier for the application.",
            "name": "The application's display name.",
            "rateLimit": "The per-application message rate limit, if set.",
            "metadata": "Arbitrary key-value metadata attached to the application.",
            "createdAt": "When the application was created.",
            "updatedAt": "When the application was last modified.",
        },
    },
    "event_types": {
        "description": "A Svix event type — the schema and metadata for a category of webhook messages your application sends.",
        "docs_url": "https://api.svix.com/docs",
        "columns": {
            "name": "The unique name of the event type (e.g. `invoice.paid`).",
            "description": "A human-readable description of the event type.",
            "schemas": "The JSON schema(s) describing the payload for this event type.",
            "archived": "Whether the event type has been archived.",
            "deprecated": "Whether the event type is marked as deprecated.",
            "featureFlag": "The feature flag gating this event type, if any.",
            "groupName": "The group the event type belongs to, used for organising event types.",
            "createdAt": "When the event type was created.",
            "updatedAt": "When the event type was last modified.",
        },
    },
}
