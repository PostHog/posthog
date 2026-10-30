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
    "locations": {
        "description": "A physical location that job offers in Recruitee are assigned to.",
        "docs_url": "https://docs.recruitee.com/reference/locations",
        "columns": {
            "id": "The unique ID of the location, used by job offers to refer to it.",
            "name": "The name of the location.",
            "country_code": "The ISO 3166 country code of the location.",
            "state_name": "The name of the state or region.",
            "state_code": "The short code of the state or region.",
            "city": "The city of the location.",
            "street": "The street of the location.",
            "postal_code": "The postal code of the location.",
            "full_address": "The one-line address: country, state, city, postal code, and street.",
            "created_at": "When the location was created.",
            "updated_at": "When the location was last edited.",
            "archived_at": "When the location was archived, or null if it is active.",
            "lang_code": "The default language code of the location.",
            "active_offers_count": "The number of offers the location is assigned to.",
            "active_requisitions_count": "The number of requisitions the location is assigned to.",
            "is_deletable": "Whether the location can be deleted. It cannot while offers still use it.",
            "translations": "The translated fields of the location, one object for each language.",
        },
    },
    "candidate_notes": {
        "description": "A note that a recruiter or team member wrote on a candidate's profile.",
        "docs_url": "https://docs.recruitee.com/reference/candidatesidnotes",
        "columns": {
            "id": "The unique ID of the note.",
            "candidate_id": "The ID of the candidate the note belongs to.",
            "admin_id": "The ID of the team member who wrote the note.",
            "offer_id": "The ID of the offer the note relates to, if any.",
            "body": "The content of the note.",
            "body_html": "The content of the note as HTML.",
            "visibility": "Who can see the note: a level plus any allowed team member and role IDs.",
            "replies": "The replies to the note.",
            "reply_to_id": "The ID of the note this note replies to, if any.",
            "attachments": "The files attached to the note.",
            "pinned_at": "When the note was pinned, or null if it is not pinned.",
            "created_at": "When the note was created.",
            "updated_at": "When the note was last updated.",
        },
    },
}
