from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Opinion Stage Public Result API (JSON:API). Rows are the raw JSON:API
# resource objects, so the top-level columns are `id`, `type`, and the nested `attributes` object.
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "items": {
        "description": "An Opinion Stage item — an interactive content widget such as a quiz, survey, form, or poll. (The poll format is not returned by this API.)",
        "docs_url": "https://www.opinionstage.com/",
        "columns": {
            "id": "The unique ID of the item (widget), as the JSON:API resource identifier.",
            "type": "The JSON:API resource type for the object (for example, 'items').",
            "attributes": "The item's attributes, including its title, content format/kind, publication state, and created/modified timestamps.",
        },
    },
}
