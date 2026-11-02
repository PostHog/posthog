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
    "events": {
        "description": "An activity in your PersistIQ account, such as a lead being created, a message being sent, opened, clicked, or replied to, or a campaign change.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the event.",
            "kind": "The type of event (e.g. lead_created, message_sent, message_opened, message_received).",
            "event_at": "When the event happened.",
            "user_id": "The ID of the user who performed the event.",
            "user": "The user who performed the event (id, name, email).",
            "campaign": "The campaign the event relates to (id, name), if any.",
            "lead": "The lead the event relates to (id, email, first and last name), if any.",
            "params": "The attributes supplied with the event, if any.",
            "diff": "The changes made by the event, if any.",
        },
    },
    "lead_statuses": {
        "description": "A lead status defined for your PersistIQ account (e.g. engaged, working, unresponsive).",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the lead status.",
            "name": "The name of the lead status.",
        },
    },
    "lead_fields": {
        "description": "A lead field defined for your PersistIQ account, including custom fields.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the lead field.",
            "name": "The key of the field in a lead's data.",
            "label": "The display label of the field.",
        },
    },
    "dnc_domains": {
        "description": "A Do Not Contact domain. PersistIQ does not send email to addresses at this domain.",
        "docs_url": "https://apidocs.persistiq.com",
        "columns": {
            "id": "The unique ID of the Do Not Contact domain.",
            "name": "The domain name.",
        },
    },
}
