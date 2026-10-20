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
    "campaign_reports": {
        "description": "Per-contact engagement events for a campaign, materialized one row per (campaign, status, contact). Each documented report status is fetched separately and the status is attached to the row.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "campaign_id": "Identifier of the campaign the report covers.",
            "status": "Report status the row belongs to: sent, opened, clicked, bounced, complained, unsubscribed, not-opened or not-clicked.",
            "contact_id": "Identifier of the contact the event relates to.",
            "contact_email_address": "Email address of the contact the event relates to.",
            "occurred_at": "ISO 8601 timestamp of when the event occurred.",
        },
    },
    "campaign_report_summaries": {
        "description": "Headline performance metrics for a campaign, one row per campaign that has started sending.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "id": "Identifier of the campaign the summary covers.",
            "sent": "Number of contacts the campaign was sent to.",
            "bounced": "Bounce counts, split into hard and soft bounces.",
            "opened": "Open counts, split into total opens and unique openers.",
            "clicked": "Click counts, split into total clicks and unique clickers.",
            "complained": "Number of contacts who marked the campaign as spam.",
            "unsubscribed": "Number of contacts who unsubscribed from the campaign.",
        },
    },
    "campaign_report_links": {
        "description": "Click performance of each link in a campaign, one row per (campaign, link URL).",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "campaign_id": "Identifier of the campaign the link appeared in.",
            "url": "Destination URL of the link.",
            "clicked_total": "Number of total clicks on the link.",
            "clicked_unique": "Number of contacts who clicked the link at least once.",
        },
    },
    "list_tags": {
        "description": "Tags defined on a list, one row per (list, tag). Resolves the tags carried on contact rows.",
        "docs_url": "https://emailoctopus.com/api-documentation/v2",
        "columns": {
            "list_id": "Identifier of the list the tag is defined on.",
            "tag": "Name of the tag.",
        },
    },
}
