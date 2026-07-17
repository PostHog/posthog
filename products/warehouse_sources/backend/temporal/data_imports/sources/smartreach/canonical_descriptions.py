from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the SmartReach API docs (https://smartreach.io/apidocs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "prospects": {
        "description": "A SmartReach prospect — a contact stored in the account, targetable by outreach campaigns.",
        "docs_url": "https://smartreach.io/apidocs",
        "columns": {
            "id": "The unique ID of the prospect.",
            "email": "The primary email address of the prospect.",
            "first_name": "The prospect's first name.",
            "last_name": "The prospect's last name.",
            "company": "The company the prospect is associated with.",
            "title": "The prospect's job title.",
            "phone": "The prospect's phone number.",
            "city": "The prospect's city.",
            "state": "The prospect's state or region.",
            "country": "The prospect's country.",
            "timezone": "The prospect's time zone.",
            "linkedin_url": "The prospect's LinkedIn profile URL.",
            "category": "The prospect's category or status (e.g. active, bounced, unsubscribed).",
            "list_id": "The ID of the prospect list the prospect belongs to.",
            "owner_id": "The ID of the account user who owns the prospect.",
            "created_at": "The timestamp when the prospect was created.",
            "updated_at": "The timestamp when the prospect was last updated.",
        },
    },
    "campaigns": {
        "description": "A SmartReach campaign — an outreach sequence that sends steps to enrolled prospects.",
        "docs_url": "https://smartreach.io/apidocs",
        "columns": {
            "id": "The unique ID of the campaign.",
            "name": "The name of the campaign.",
            "status": "The current status of the campaign (e.g. active, paused, completed, draft).",
            "type": "The channel/type of the campaign (e.g. email).",
            "owner_id": "The ID of the account user who owns the campaign.",
            "team_id": "The ID of the team the campaign belongs to.",
            "prospect_count": "The number of prospects enrolled in the campaign.",
            "created_at": "The timestamp when the campaign was created.",
            "updated_at": "The timestamp when the campaign was last updated.",
        },
    },
}
