"""Canonical, documentation-sourced descriptions for Mailgun endpoints and columns.

Sourced from the official Mailgun API reference (https://documentation.mailgun.com/docs/mailgun/api-reference/).
Keyed by the endpoint names in `settings.py` `MAILGUN_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mailgun table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "domains": {
        "description": "A sending domain configured on the Mailgun account.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Domains/",
        "columns": {
            "id": "Unique identifier for the domain.",
            "name": "The domain name (e.g. mg.example.com).",
            "type": "The domain type (custom or sandbox).",
            "state": "The verification state of the domain (active, unverified, disabled).",
            "is_disabled": "Whether the domain is disabled.",
            "created_at": "Time the domain was created.",
            "smtp_login": "The SMTP login (username) for the domain.",
            "web_prefix": "The prefix used for tracking and unsubscribe links.",
            "web_scheme": "The URL scheme used for tracking links (http or https).",
            "spam_action": "How spam is handled for the domain (disabled, block, tag).",
            "wildcard": "Whether the domain accepts mail for all subdomains.",
            "skip_verification": "Whether the TLS certificate and hostname are not verified when delivering mail for the domain.",
        },
    },
    "events": {
        "description": "An event in the Mailgun event log (delivered, opened, clicked, bounced, etc.) for a domain.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Events/",
        "columns": {
            "id": "Unique identifier for the event.",
            "domain": "The sending domain the event belongs to.",
            "event": "The event type (accepted, delivered, opened, clicked, failed, complained, etc.).",
            "timestamp": "Time the event occurred, as a Unix timestamp.",
            "recipient": "The recipient email address the event relates to.",
            "message": "Details about the message that generated the event.",
            "tags": "The tags associated with the message.",
            "campaigns": "The campaigns associated with the message.",
            "delivery-status": "Delivery status details, including SMTP response codes.",
            "severity": "Severity of a failure event (temporary or permanent).",
            "reason": "The reason a delivery failed, if applicable.",
        },
    },
    "bounces": {
        "description": "A bounced recipient address recorded for a domain in Mailgun's suppression list.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Suppressions/",
        "columns": {
            "domain": "The sending domain the bounce belongs to.",
            "address": "The recipient email address that bounced.",
            "code": "The SMTP error code returned for the bounce.",
            "error": "The error message describing why the address bounced.",
            "created_at": "Time the bounce was recorded.",
        },
    },
    "complaints": {
        "description": "A spam complaint recorded for a domain in Mailgun's suppression list.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Suppressions/",
        "columns": {
            "domain": "The sending domain the complaint belongs to.",
            "address": "The recipient email address that filed the complaint.",
            "created_at": "Time the complaint was recorded.",
        },
    },
    "unsubscribes": {
        "description": "An unsubscribed recipient address recorded for a domain in Mailgun's suppression list.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Suppressions/",
        "columns": {
            "domain": "The sending domain the unsubscribe belongs to.",
            "address": "The recipient email address that unsubscribed.",
            "tags": "The tags the address unsubscribed from.",
            "created_at": "Time the unsubscribe was recorded.",
        },
    },
    "mailing_lists": {
        "description": "A mailing list configured on the Mailgun account, addressable by a single list address.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Mailing-Lists/",
        "columns": {
            "address": "The email address of the mailing list.",
            "name": "The display name of the mailing list.",
            "description": "A description of the mailing list.",
            "members_count": "The number of members in the mailing list.",
            "access_level": "Who can post to the list (readonly, members, everyone).",
            "created_at": "Time the mailing list was created.",
        },
    },
    "tags": {
        "description": "A tag used to categorize and track messages for a domain in Mailgun.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Tags/",
        "columns": {
            "domain": "The sending domain the tag belongs to.",
            "tag": "The tag string.",
            "description": "A description of the tag.",
            "first-seen": "Time the tag was first used.",
            "last-seen": "Time the tag was last used.",
        },
    },
    "templates": {
        "description": "A stored, reusable message template for a domain in Mailgun.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Templates/",
        "columns": {
            "domain": "The sending domain the template belongs to.",
            "name": "The name of the template.",
            "description": "A description of the template.",
            "createdAt": "Time the template was created.",
            "version": "The version details of the template's stored content.",
        },
    },
}
