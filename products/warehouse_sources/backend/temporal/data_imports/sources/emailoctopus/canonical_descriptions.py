from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the EmailOctopus v2 API docs (https://emailoctopus.com/api-documentation/v2). The
# schema is fixed across teams, so document it once rather than paying an LLM to re-derive it.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "lists": {
        "description": "A list of contacts that campaigns and automations send to.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "Name of the list.",
            "double_opt_in": "Whether new contacts must confirm their subscription before being marked subscribed.",
            "fields": "Custom fields defined on the list, each with a tag, label, type and fallback.",
            "tags": "Tags configured on the list.",
            "counts": "Contact counts on the list, broken down by status (subscribed, unsubscribed, pending).",
            "created_at": "ISO 8601 timestamp of when the list was created.",
        },
    },
    "campaigns": {
        "description": "An email campaign sent to one or more lists.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "status": "Current status of the campaign (e.g. draft, sending, sent).",
            "name": "Internal name of the campaign.",
            "subject": "Subject line of the campaign email.",
            "from": "Sender name and email address the campaign is sent from.",
            "to": "Lists the campaign is or was sent to.",
            "content": "Rendered HTML and plain-text content of the campaign.",
            "created_at": "ISO 8601 timestamp of when the campaign was created.",
            "sent_at": "ISO 8601 timestamp of when the campaign was sent, if it has been sent.",
        },
    },
    "contacts": {
        "description": "A contact belonging to a list, materialized one row per (list, contact). The list_id is attached to each row so a contact that appears on multiple lists stays distinct.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "id": "Identifier for the contact, an MD5 hash of the lowercase email address. Unique within a list.",
            "list_id": "Identifier of the list this contact belongs to.",
            "email_address": "Email address of the contact.",
            "fields": "Values of the list's custom fields for this contact.",
            "tags": "Tags applied to the contact.",
            "status": "Subscription status of the contact (subscribed, unsubscribed or pending).",
            "created_at": "ISO 8601 timestamp of when the contact was added to the list.",
            "last_updated_at": "ISO 8601 timestamp of when the contact was last updated.",
        },
    },
}
