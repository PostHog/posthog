from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Zenloop public API docs (https://docs.zenloop.com/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "A Zenloop survey (measurement) — an NPS or feedback questionnaire that collects answers from recipients.",
        "docs_url": "https://docs.zenloop.com/reference/get-surveys",
        "columns": {
            "id": "The unique numeric ID of the survey.",
            "public_hash_id": "The stable public hash identifier of the survey, used to scope answer queries.",
            "title": "The human-readable title of the survey.",
            "status": "The current status of the survey (e.g. draft, live, paused).",
            "type": "The survey type (e.g. the metric or question format it measures).",
            "inserted_at": "The timestamp when the survey was created.",
            "updated_at": "The timestamp when the survey was last updated.",
        },
    },
    "survey_groups": {
        "description": "A Zenloop survey group — a bundle of surveys aggregated together for combined reporting.",
        "docs_url": "https://docs.zenloop.com/reference/get-survey-groups",
        "columns": {
            "id": "The unique numeric ID of the survey group.",
            "public_hash_id": "The stable public hash identifier of the survey group.",
            "title": "The human-readable title of the survey group.",
            "status": "The current status of the survey group.",
            "inserted_at": "The timestamp when the survey group was created.",
            "updated_at": "The timestamp when the survey group was last updated.",
        },
    },
    "properties": {
        "description": "A Zenloop property — a custom metadata field attached to survey answers for segmentation and filtering.",
        "docs_url": "https://docs.zenloop.com/reference/get-properties",
        "columns": {
            "id": "The unique numeric ID of the property.",
            "name": "The name of the property.",
            "inserted_at": "The timestamp when the property was created.",
            "updated_at": "The timestamp when the property was last updated.",
        },
    },
}
