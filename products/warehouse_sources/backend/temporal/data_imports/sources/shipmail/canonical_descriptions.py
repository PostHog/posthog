"""Canonical descriptions sourced from the Shipmail API documentation."""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "messages": {
        "description": "Analytics-safe message records in stable update order, without message content or sensitive headers.",
        "docs_url": "https://shipmail.to/docs/api/messages",
        "columns": {
            "object": "The API object type. Always `message_analytics`.",
            "id": "Unique identifier for the message.",
            "mailbox_id": "Identifier of the mailbox associated with the message.",
            "thread_id": "Identifier of the conversation thread, when available.",
            "client_reference": "Caller-provided reference used to associate the message with an external record.",
            "direction": "Whether the message was inbound or outbound.",
            "contact_addresses": "Email addresses of contacts involved in the message.",
            "recipient_count": "Number of recipients on the message.",
            "attachment_count": "Number of attachments on the message.",
            "source": "System or integration that created the message.",
            "mode": "Whether the message belongs to live or sandbox data.",
            "status": "Current message status.",
            "scheduled_at": "Time at which the message was scheduled to be sent, when applicable.",
            "created_at": "Time at which the message was created.",
            "updated_at": "Time at which the message was last updated.",
        },
    },
    "mailboxes": {
        "description": "Mailboxes belonging to the authenticated Shipmail organization.",
        "docs_url": "https://shipmail.to/docs/api/mailboxes",
        "columns": {
            "object": "The API object type. Always `mailbox`.",
            "id": "Unique identifier for the mailbox.",
            "domain_id": "Identifier of the domain that hosts the mailbox.",
            "address": "Email address of the mailbox.",
            "display_name": "Display name used for the mailbox.",
            "suspended_at": "Time at which the mailbox was suspended, when applicable.",
            "suspension_reasons": "Reasons the mailbox is suspended.",
            "spam_filter_threshold": "Spam score threshold applied to inbound messages.",
            "auto_reply": "Automatic reply configuration for the mailbox.",
            "created_at": "Time at which the mailbox was created.",
            "updated_at": "Time at which the mailbox was last updated.",
        },
    },
    "domains": {
        "description": "Sending and receiving domains configured in the authenticated Shipmail organization.",
        "docs_url": "https://shipmail.to/docs/api/domains",
        "columns": {
            "object": "The API object type. Always `domain`.",
            "id": "Unique identifier for the domain.",
            "name": "Domain name.",
            "status": "Current domain status.",
            "managed_by": "Whether DNS is managed externally or by Shipmail.",
            "dns_provider": "Detected DNS provider, when available.",
            "mx_verified": "Whether the MX record is verified.",
            "spf_verified": "Whether the SPF record is verified.",
            "dkim_verified": "Whether the DKIM record is verified.",
            "dmarc_verified": "Whether the DMARC record is verified.",
            "dmarc_managed_externally": "Whether DMARC is managed outside Shipmail.",
            "outbound_verified": "Whether outbound sending is verified.",
            "catch_all_mailbox_id": "Identifier of the catch-all mailbox, when configured.",
            "verified_at": "Time at which the domain completed verification.",
            "created_at": "Time at which the domain was created.",
            "updated_at": "Time at which the domain was last updated.",
            "registration": "Registration details for domains managed by Shipmail, when available.",
        },
    },
    "suppressions": {
        "description": "Email addresses suppressed from outbound delivery.",
        "docs_url": "https://shipmail.to/docs/api/suppressions",
        "columns": {
            "object": "The API object type. Always `suppression`.",
            "email_address": "Suppressed email address.",
            "reason": "Reason the address was suppressed.",
            "created_at": "Time at which the suppression was created.",
        },
    },
}
