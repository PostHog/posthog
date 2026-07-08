"""Canonical, documentation-sourced descriptions for SendGrid endpoints and columns.

Sourced from the official Twilio SendGrid v3 API reference
(https://www.twilio.com/docs/sendgrid/api-reference). Keyed by the schema names in `settings.py`
`SENDGRID_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced SendGrid table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Shared shape of the suppression endpoints (bounces, blocks, invalid emails, spam reports).
_SUPPRESSION_COLUMNS = {
    "email": "The email address that was suppressed.",
    "created": "Time at which the suppression record was created, as a Unix timestamp.",
    "reason": "Reason the email was suppressed.",
    "status": "Status code associated with the suppression event.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "bounces": {
        "description": "Email addresses that bounced — the receiving server rejected the message.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/bounces-api/retrieve-all-bounces",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "blocks": {
        "description": "Email addresses blocked due to temporary delivery issues such as a full mailbox or server outage.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/blocks-api/retrieve-all-blocks",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "invalid_emails": {
        "description": "Email addresses that are invalid or malformed and cannot receive mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/invalid-e-mails-api/retrieve-all-invalid-emails",
        "columns": dict(_SUPPRESSION_COLUMNS),
    },
    "spam_reports": {
        "description": "Email addresses of recipients who marked your mail as spam.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/spam-reports-api/retrieve-all-spam-reports",
        "columns": {
            "email": "The email address that reported the message as spam.",
            "created": "Time at which the spam report was recorded, as a Unix timestamp.",
            "ip": "IP address the message was sent from.",
        },
    },
    "global_unsubscribes": {
        "description": "Email addresses on the global unsubscribe list, suppressed from all future mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/suppressions-global-suppressions/retrieve-all-global-suppressions",
        "columns": {
            "email": "The globally unsubscribed email address.",
            "created": "Time at which the address was added to the global unsubscribe list, as a Unix timestamp.",
        },
    },
    "unsubscribe_groups": {
        "description": "Suppression (unsubscribe) groups used to let recipients opt out of specific categories of mail.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/suppressions-unsubscribe-groups/retrieve-all-suppression-groups-associated-with-the-user",
        "columns": {
            "id": "Unique identifier for the unsubscribe group.",
            "name": "Name of the unsubscribe group.",
            "description": "Description of the unsubscribe group.",
            "is_default": "Whether this is the default unsubscribe group.",
            "unsubscribes": "Number of unsubscribes recorded against this group.",
        },
    },
    "marketing_lists": {
        "description": "Marketing contact lists used to segment recipients for campaigns.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/lists/get-all-lists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "Name of the list.",
            "contact_count": "Number of contacts on the list.",
        },
    },
    "templates": {
        "description": "Email templates (legacy and dynamic) used to compose messages.",
        "docs_url": "https://www.twilio.com/docs/sendgrid/api-reference/transactional-templates/retrieve-paged-transactional-templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "Name of the template.",
            "generation": "Template generation: legacy or dynamic.",
            "updated_at": "Time at which the template was last updated.",
            "versions": "List of versions belonging to the template.",
        },
    },
}
