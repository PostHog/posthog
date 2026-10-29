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
    "hard_bounces": {
        "description": "Recipients on the account's hard bounce suppression list. MailerSend skips sending to them.",
        "docs_url": "https://developers.mailersend.com/api/v1/email/recipients#hard-bounces",
        "columns": {
            "id": "Unique identifier for the suppression entry.",
            "created_at": "Timestamp when the recipient was added to the list.",
            "recipient": "Nested object for the suppressed recipient (id, email, timestamps, and its domain).",
            "reason": "Reason for the hard bounce.",
        },
    },
    "spam_complaints": {
        "description": "Recipients on the account's spam complaint suppression list. MailerSend skips sending to them.",
        "docs_url": "https://developers.mailersend.com/api/v1/email/recipients#spam-complaints",
        "columns": {
            "id": "Unique identifier for the suppression entry.",
            "created_at": "Timestamp when the recipient was added to the list.",
            "recipient": "Nested object for the suppressed recipient (id, email, timestamps, and its domain).",
        },
    },
    "unsubscribes": {
        "description": "Recipients on the account's unsubscribe suppression list. MailerSend skips sending to them.",
        "docs_url": "https://developers.mailersend.com/api/v1/email/recipients#unsubscribes",
        "columns": {
            "id": "Unique identifier for the suppression entry.",
            "created_at": "Timestamp when the recipient was added to the list.",
            "recipient": "Nested object for the suppressed recipient (id, email, timestamps, and its domain).",
            "reason": "Unsubscribe reason code (e.g. NEVER_SIGNED).",
            "readable_reason": "Human-readable unsubscribe reason.",
        },
    },
    "analytics_by_date": {
        "description": "Account-wide email event counts per day. Every day in the synced range has a row, with 0 for days without events. Retained for 6 months.",
        "docs_url": "https://developers.mailersend.com/api/v1/email/analytics#activity-data-by-date",
        "columns": {
            "date": "Start of the day (UTC) the counts cover.",
            "queued": "Number of emails queued.",
            "sent": "Number of emails sent.",
            "delivered": "Number of emails delivered.",
            "soft_bounced": "Number of soft bounces.",
            "hard_bounced": "Number of hard bounces.",
            "deferred": "Number of deferred deliveries.",
            "opened": "Number of opens.",
            "clicked": "Number of clicks.",
            "unsubscribed": "Number of unsubscribes.",
            "spam_complaints": "Number of spam complaints.",
            "survey_opened": "Number of survey opens.",
            "survey_submitted": "Number of survey submissions.",
            "opened_unique": "Number of unique opens.",
            "clicked_unique": "Number of unique clicks.",
        },
    },
}
