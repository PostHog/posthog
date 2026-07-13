from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Simplecast API docs (https://apidocs.simplecast.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "podcasts": {
        "description": "A podcast (show) hosted on Simplecast that the account's token can access.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the podcast.",
            "title": "The podcast's title.",
            "account_id": "The ID of the account that owns the podcast.",
            "status": "The publication status of the podcast.",
            "episodes": "A reference to the podcast's episodes collection.",
            "created_at": "When the podcast was created.",
            "updated_at": "When the podcast was last updated.",
            "href": "The API URL of the podcast resource.",
        },
    },
}
