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
    "responses": {
        "description": "A single submission of an Opinion Stage item by a respondent, with the answer to each question.",
        "docs_url": "https://api.opinionstage.com/api-docs/api/v2/openapi.yaml",
        "columns": {
            "id": "The unique identifier for the response.",
            "item_id": "The ID of the item (widget) that the response belongs to.",
            "type": "The JSON:API resource type. Always 'responses'.",
            "attributes": "The response's attributes: creation timestamp, the answers (question ID, selected options, free text, checked flag), the result shown, the UTM source, and the completion duration.",
            "links": "Links to the response in the API and to the page that hosts the item.",
        },
    },
    "questions": {
        "description": "A question of an Opinion Stage item. Use it to resolve the question IDs on response answers.",
        "docs_url": "https://api.opinionstage.com/api-docs/api/v2/openapi.yaml",
        "columns": {
            "id": "The unique identifier for the question.",
            "item_id": "The ID of the item (widget) that the question belongs to.",
            "type": "The JSON:API resource type. Always 'questions'.",
            "attributes": "The question's attributes: title, kind (text, select, or boolean), whether it is part of the lead form, and created/modified timestamps.",
        },
    },
}
