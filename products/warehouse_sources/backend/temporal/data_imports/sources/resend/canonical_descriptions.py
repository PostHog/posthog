"""Canonical, documentation-sourced descriptions for Resend endpoints and columns.

Sourced from the official Resend API reference (https://resend.com/docs/api-reference).
Keyed by the endpoint names in `settings.py` `RESEND_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Resend table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "audiences": {
        "description": "A list of contacts you can send broadcast emails to.",
        "docs_url": "https://resend.com/docs/api-reference/audiences/list-audiences",
        "columns": {
            "id": "Unique identifier for the audience.",
            "name": "The audience's name.",
            "created_at": "Time at which the audience was created.",
        },
    },
    "broadcasts": {
        "description": "An email campaign sent to an audience.",
        "docs_url": "https://resend.com/docs/api-reference/broadcasts/list-broadcasts",
        "columns": {
            "id": "Unique identifier for the broadcast.",
            "name": "The broadcast's name.",
            "audience_id": "ID of the audience the broadcast is sent to.",
            "from": "The sender email address for the broadcast.",
            "subject": "Subject line of the broadcast email.",
            "reply_to": "Reply-to address for the broadcast.",
            "preview_text": "Preview text shown in recipients' inboxes.",
            "status": "Status of the broadcast (e.g. draft, sent).",
            "created_at": "Time at which the broadcast was created.",
            "scheduled_at": "Time at which the broadcast is scheduled to send.",
            "sent_at": "Time at which the broadcast was sent.",
        },
    },
    "domains": {
        "description": "A sending domain configured in Resend for authenticated email delivery.",
        "docs_url": "https://resend.com/docs/api-reference/domains/list-domains",
        "columns": {
            "id": "Unique identifier for the domain.",
            "name": "The domain name.",
            "status": "Verification status of the domain (e.g. pending, verified, failed).",
            "region": "The region the domain sends from.",
            "records": "DNS records required to verify and authenticate the domain.",
            "created_at": "Time at which the domain was created.",
        },
    },
    "emails": {
        "description": "A transactional email sent through Resend.",
        "docs_url": "https://resend.com/docs/api-reference/emails/retrieve-email",
        "columns": {
            "id": "Unique identifier for the email.",
            "from": "The sender email address.",
            "to": "List of recipient email addresses.",
            "cc": "List of CC recipient email addresses.",
            "bcc": "List of BCC recipient email addresses.",
            "reply_to": "Reply-to address for the email.",
            "subject": "Subject line of the email.",
            "html": "HTML body of the email.",
            "text": "Plain-text body of the email.",
            "last_event": "The most recent delivery event for the email (e.g. delivered, bounced).",
            "created_at": "Time at which the email was created.",
        },
    },
    "contacts": {
        "description": "A contact belonging to an audience, with subscription status.",
        "docs_url": "https://resend.com/docs/api-reference/contacts/list-contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
            "audience_id": "ID of the audience the contact belongs to.",
            "email": "The contact's email address.",
            "first_name": "The contact's first name.",
            "last_name": "The contact's last name.",
            "unsubscribed": "Whether the contact has unsubscribed.",
            "created_at": "Time at which the contact was created.",
        },
    },
}
