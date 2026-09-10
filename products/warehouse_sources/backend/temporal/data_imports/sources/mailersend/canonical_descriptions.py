from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the MailerSend public API docs (https://developers.mailersend.com/api/v1/).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "domains": {
        "description": "Sending domains configured in your MailerSend account, with their verification and DNS status.",
        "docs_url": "https://developers.mailersend.com/api/v1/domains.html",
        "columns": {
            "id": "Unique identifier for the domain.",
            "name": "The domain name (e.g. mail.example.com).",
            "dkim": "Whether DKIM authentication is configured for the domain.",
            "spf": "Whether SPF authentication is configured for the domain.",
            "tracking": "Whether open/click tracking is enabled for the domain.",
            "is_verified": "Whether the domain has passed verification and can send mail.",
            "is_cname_verified": "Whether the domain's CNAME records are verified.",
            "is_dns_active": "Whether the domain's DNS records are active.",
            "created_at": "Timestamp when the domain was added.",
            "updated_at": "Timestamp when the domain was last updated.",
        },
    },
    "recipients": {
        "description": "Recipients that have been sent email through your MailerSend account.",
        "docs_url": "https://developers.mailersend.com/api/v1/recipients.html",
        "columns": {
            "id": "Unique identifier for the recipient.",
            "email": "The recipient's email address.",
            "created_at": "Timestamp when the recipient was first seen.",
            "updated_at": "Timestamp when the recipient was last updated.",
            "deleted_at": "Timestamp when the recipient was deleted, if applicable.",
        },
    },
    "templates": {
        "description": "Email templates available in your MailerSend account.",
        "docs_url": "https://developers.mailersend.com/api/v1/templates.html",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "Human-readable template name.",
            "type": "Template type (e.g. html or drag-drop).",
            "image_path": "URL of the template's preview image.",
            "created_at": "Timestamp when the template was created.",
        },
    },
    "messages": {
        "description": "Messages submitted to the MailerSend API. Each row is one send request, which may fan out to multiple recipients and activity events.",
        "docs_url": "https://developers.mailersend.com/api/v1/messages.html",
        "columns": {
            "id": "Unique identifier for the message.",
            "created_at": "Timestamp when the message was submitted.",
            "updated_at": "Timestamp when the message was last updated.",
        },
    },
    "activity": {
        "description": "Per-recipient email activity events (sent, delivered, opened, clicked, bounced, etc.) for a sending domain. Retained for 1-30 days depending on plan.",
        "docs_url": "https://developers.mailersend.com/api/v1/activity.html",
        "columns": {
            "id": "Unique identifier for the activity event.",
            "domain_id": "Identifier of the sending domain this event belongs to (added by PostHog so the row's primary key is unique across domains).",
            "type": "Event type: sent, delivered, soft_bounced, hard_bounced, opened, clicked, unsubscribed, spam_complaint, etc.",
            "created_at": "Timestamp when the event occurred.",
            "updated_at": "Timestamp when the event was last updated.",
            "email": "Nested object describing the email this event relates to (subject, status, recipient, tags, ...).",
        },
    },
}
