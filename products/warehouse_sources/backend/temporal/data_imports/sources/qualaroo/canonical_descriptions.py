from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Qualaroo REST Reporting API docs
# (https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "nudges": {
        "description": "A Qualaroo nudge (survey) configured in your account.",
        "docs_url": "https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API",
        "columns": {
            "id": "The unique ID of the nudge (survey).",
            "name": "The internal name of the nudge.",
            "alias": "The human-readable alias of the nudge.",
            "type": "The nudge type (for example, survey or exit).",
            "status": "The current status of the nudge (for example, active or paused).",
            "created_at": "When the nudge was created.",
            "updated_at": "When the nudge was last updated.",
        },
    },
}
