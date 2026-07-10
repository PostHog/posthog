from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the ConfigCat Public Management API docs
# (https://api.configcat.com/docs). Partial coverage is fine — uncovered columns fall back to LLM
# enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A ConfigCat product — the top-level container that groups configs, environments, and feature flags.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "productId": "The unique identifier (GUID) of the product.",
            "name": "The name of the product.",
            "description": "The description of the product.",
            "order": "The display order of the product within the organization.",
            "reasonRequired": "Whether a mandatory reason is required for changes in this product.",
            "organization": "The organization that owns the product (nested object with organizationId and name).",
        },
    },
    "organizations": {
        "description": "A ConfigCat organization — the account-level owner of products and members.",
        "docs_url": "https://api.configcat.com/docs",
        "columns": {
            "organizationId": "The unique identifier (GUID) of the organization.",
            "name": "The name of the organization.",
        },
    },
}
