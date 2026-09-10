"""Canonical, documentation-sourced descriptions for Campayn endpoints and columns.

Sourced from the official Campayn API reference (https://github.com/nebojsac/Campayn-API). Keyed by the
table names in `settings.py` `CAMPAYN_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Campayn table. Columns absent here fall back to LLM enrichment. The official docs are explicitly
preliminary (several TODO sections), so coverage is intentionally conservative.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_BASE = "https://github.com/nebojsac/Campayn-API/blob/master/endpoints"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "lists": {
        "description": "A contact list visible to the authenticated account.",
        "docs_url": f"{_DOCS_BASE}/lists.md",
        "columns": {
            "id": "Unique identifier for the list.",
            "list_name": "Display name of the list.",
            "tags": "Comma-separated tags applied to the list.",
            "contact_count": "Number of contacts currently in the list.",
        },
    },
    "contacts": {
        "description": "A contact belonging to a list. Fetched per list, so each row carries the parent list_id; the same contact can appear under multiple lists.",
        "docs_url": f"{_DOCS_BASE}/contacts.md",
        "columns": {
            "id": "Unique identifier for the contact.",
            "list_id": "Identifier of the list this contact row was fetched from (injected by PostHog).",
            "email": "The contact's email address.",
            "first_name": "The contact's first name.",
            "last_name": "The contact's last name.",
            "image_url": "URL of the contact's profile image.",
        },
    },
    "forms": {
        "description": "A signup form associated with a list (signup page, embed, WordPress, or Facebook form).",
        "docs_url": f"{_DOCS_BASE}/forms.md",
        "columns": {
            "id": "Unique identifier for the form.",
            "list_id": "Identifier of the list this form row was fetched from (injected by PostHog).",
            "contact_list_id": "Identifier of the list the form is associated with.",
            "form_title": "Display title of the form.",
            "form_type": "Form type code: 0 signup page, 1 embed signup, 2 WordPress signup, 3 Facebook signup.",
            "form_html": "Rendered HTML of the form, when available.",
            "signup_count": "Number of signups collected through the form.",
        },
    },
    "emails": {
        "description": "An email (campaign) visible to the account, with basic delivery and engagement stats.",
        "docs_url": f"{_DOCS_BASE}/emails.md",
        "columns": {
            "id": "Unique identifier for the email.",
            "name": "Internal name of the email.",
            "scheduled_date": "When the email is scheduled to send, if scheduled.",
            "send_now": "Whether the email is set to send immediately.",
            "send_count": "Number of recipients the email was sent to.",
            "campaign_title": "Title of the campaign the email belongs to, if any.",
            "status": "Delivery status of the email (e.g. delivered, incomplete).",
            "unique_views": "Count of unique recipients who opened the email.",
            "unique_responses": "Count of unique recipients who clicked through.",
            "percent_views": "Percentage of recipients who opened the email.",
            "percent_responses": "Percentage of recipients who clicked through.",
            "preview_url": "URL to a hosted preview of the email.",
            "preview_thumb": "URL to a thumbnail image of the email.",
        },
    },
    "reports": {
        "description": "Calendar of sent and scheduled emails with their report URLs. Scheduled emails have no report URL.",
        "docs_url": f"{_DOCS_BASE}/reports.md",
        "columns": {
            "id": "Identifier of the email the report refers to.",
            "name": "Name of the email.",
            "scheduled_date": "When the email was sent or is scheduled to send (UTC).",
            "status": "Status of the email (e.g. sent).",
            "preview_url": "URL to a hosted preview of the email.",
            "report_url": "URL to the email's report; null for scheduled (not yet sent) emails.",
        },
    },
}
