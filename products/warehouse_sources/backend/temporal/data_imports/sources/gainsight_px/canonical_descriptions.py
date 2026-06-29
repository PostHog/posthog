from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the Gainsight PX REST API docs (https://px-apidocs.gainsight.com). Table-level
# descriptions and the `id` primary key are stated authoritatively; the remaining columns are left to
# LLM enrichment (seeded with `docs_url`) rather than asserting field names we have not verified
# against a live PX response.
_DOCS_URL = "https://px-apidocs.gainsight.com"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "An account (the company or organization a set of users belongs to) tracked in Gainsight PX.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the account (the customer-supplied account id).",
        },
    },
    "users": {
        "description": "An end user tracked in Gainsight PX, typically associated with an account.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the user (the customer-supplied user id, often an email).",
        },
    },
    "segments": {
        "description": "A saved segment — a rule-based grouping of users or accounts used to target engagements and analytics.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the segment.",
        },
    },
    "features": {
        "description": "A tracked product feature and its adoption data in Gainsight PX.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the feature.",
        },
    },
    "articles": {
        "description": "A Knowledge Center article surfaced to users in-app through Gainsight PX.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the article.",
        },
    },
    "kcbots": {
        "description": "A Knowledge Center Bot configuration in Gainsight PX.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the Knowledge Center Bot.",
        },
    },
}
