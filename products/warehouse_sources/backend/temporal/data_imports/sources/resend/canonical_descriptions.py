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
    "suppressions": {
        "description": "An email address on the team's suppression list, which Resend skips when sending.",
        "docs_url": "https://resend.com/docs/api-reference/suppressions/list-suppressions",
        "columns": {
            "id": "Unique identifier for the suppression.",
            "email": "The suppressed email address.",
            "origin": "Why the address was suppressed: bounce, complaint, or manual.",
            "source_id": "ID of the email that triggered the suppression. Null for manual suppressions.",
            "created_at": "Time at which the address was suppressed.",
        },
    },
    "email_metrics": {
        "description": "Account-level email delivery and engagement metrics, one row per UTC day.",
        "docs_url": "https://resend.com/docs/api-reference/emails/get-metrics",
        "columns": {
            "period": "The UTC day the metrics cover.",
            "received": "Emails Resend accepted for processing.",
            "sent": "Emails sent to the recipient's mail server.",
            "delivered": "Emails the recipient's mail server accepted.",
            "delivery_delayed": "Deliveries postponed by a temporary issue.",
            "failed": "Emails that never reached a mail server.",
            "suppressed": "Emails skipped because the recipient is suppressed.",
            "bounced": "All bounces: transient, permanent, and undetermined.",
            "bounced_transient": "Soft bounces. A later send can succeed.",
            "bounced_permanent": "Hard bounces. The address is suppressed.",
            "bounced_undetermined": "Bounces with no classifiable reason.",
            "opened": "Open events, including repeats.",
            "unique_opened": "Emails opened at least once.",
            "clicked": "Link click events, including repeats.",
            "unique_clicked": "Emails clicked at least once.",
            "complained": "Delivered emails marked as spam.",
            "unsubscribed": "Recipients who unsubscribed.",
            "delivery_rate": "delivered / sent.",
            "open_rate": "unique_opened / delivered.",
            "click_rate": "unique_clicked / delivered.",
            "bounce_rate": "bounced / sent.",
            "complaint_rate": "complained / delivered.",
            "unsubscribe_rate": "unsubscribed / delivered.",
        },
    },
    "broadcast_clicked_links": {
        "description": "A link clicked in a broadcast, with its total and unique click counts.",
        "docs_url": "https://resend.com/docs/api-reference/broadcasts/list-broadcast-clicked-links",
        "columns": {
            "id": "Opaque pagination cursor for the row. It does not identify any entity in Resend.",
            "url": "The URL that was clicked.",
            "clicks": "Total clicks on the link, including repeat clicks by the same recipient.",
            "unique_clicks": "Number of distinct recipients who clicked the link.",
            "_broadcast_id": "ID of the broadcast the link belongs to.",
        },
    },
}
