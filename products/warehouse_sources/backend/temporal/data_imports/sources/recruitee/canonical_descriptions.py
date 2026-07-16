from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Recruitee API docs (https://docs.recruitee.com/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "candidates": {
        "description": "A person who has applied to or been sourced for a job in your Recruitee account.",
        "docs_url": "https://docs.recruitee.com/reference/candidates-index",
        "columns": {
            "id": "The unique ID of the candidate.",
            "name": "The candidate's full name.",
            "emails": "The candidate's email addresses.",
            "phones": "The candidate's phone numbers.",
            "source": "Where the candidate came from (e.g. a job board or referral).",
            "created_at": "When the candidate record was created.",
            "updated_at": "When the candidate record was last updated.",
        },
    },
    "offers": {
        "description": "A job opening (offer) posted in Recruitee that candidates apply to.",
        "docs_url": "https://docs.recruitee.com/reference/offers-index",
        "columns": {
            "id": "The unique ID of the offer.",
            "title": "The job title of the offer.",
            "status": "The current status of the offer (e.g. published, closed, draft).",
            "department_id": "The ID of the department the offer belongs to.",
            "location": "The location of the job.",
            "created_at": "When the offer was created.",
            "updated_at": "When the offer was last updated.",
        },
    },
    "departments": {
        "description": "A department that job offers and candidates are organised under.",
        "docs_url": "https://docs.recruitee.com/reference/departments-index",
        "columns": {
            "id": "The unique ID of the department.",
            "name": "The name of the department.",
            "status": "The status of the department.",
            "offers_count": "The number of offers in the department.",
        },
    },
    "placements": {
        "description": "A candidate placed onto a specific offer, capturing their position in that offer's pipeline.",
        "docs_url": "https://docs.recruitee.com/reference/placements-index",
        "columns": {
            "id": "The unique ID of the placement.",
            "candidate_id": "The ID of the placed candidate.",
            "offer_id": "The ID of the offer the candidate is placed on.",
            "stage_id": "The ID of the current pipeline stage.",
            "status": "The status of the placement (e.g. hired, rejected).",
            "created_at": "When the placement was created.",
            "updated_at": "When the placement was last updated.",
        },
    },
}
