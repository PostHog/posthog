from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the PersistIQ REST API docs (https://apidocs.persistiq.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "leads": {
        "description": "A prospect or contact in PersistIQ, targeted by outbound sales campaigns.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the lead.",
            "status": "The current status of the lead (e.g. active, finished, bounced).",
            "data": "The lead's field values (name, email, company, and any custom fields).",
            "created_at": "When the lead was created.",
            "updated_at": "When the lead was last updated.",
            "owner_id": "The ID of the user who owns the lead.",
        },
    },
    "users": {
        "description": "A member of your PersistIQ account who sends campaigns and owns leads.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "active": "Whether the user account is active.",
            "salesforce_id": "The linked Salesforce user ID, if connected.",
        },
    },
    "campaigns": {
        "description": "An outbound sales campaign (sequence of steps) that leads are enrolled in.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the campaign.",
            "name": "The name of the campaign.",
            "creator_id": "The ID of the user who created the campaign.",
            "created_at": "When the campaign was created.",
        },
    },
}
