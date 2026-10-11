"""Canonical, documentation-sourced descriptions for Mailgun endpoints and columns.

Sourced from the official Mailgun API reference (https://documentation.mailgun.com/docs/mailgun/api-reference/).
Keyed by the endpoint names in `settings.py` `MAILGUN_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mailgun table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_METRICS_DOCS_URL = (
    "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/metrics/post-v1-analytics-metrics"
)

_METRICS_COLUMNS: dict[str, str] = {
    "time": "Start of the UTC day the metrics cover.",
    "accepted_count": "Messages Mailgun accepted for delivery.",
    "processed_count": "Messages Mailgun processed, including ones it suppressed.",
    "sent_count": "Messages Mailgun attempted to deliver.",
    "delivered_count": "Messages the recipient's mail server accepted.",
    "failed_count": "Messages that failed to deliver, temporarily or permanently.",
    "temporary_failed_count": "Delivery attempts that failed temporarily and may be retried.",
    "permanent_failed_count": "Messages that failed to deliver permanently.",
    "bounced_count": "Messages that bounced.",
    "hard_bounces_count": "Messages that bounced permanently.",
    "soft_bounces_count": "Messages that bounced temporarily.",
    "opened_count": "Opens of delivered messages.",
    "unique_opened_count": "Delivered messages opened at least once.",
    "clicked_count": "Clicks on tracked links.",
    "unique_clicked_count": "Delivered messages with at least one tracked link clicked.",
    "unsubscribed_count": "Recipients who unsubscribed.",
    "complained_count": "Recipients who reported a message as spam.",
    "delivered_rate": "Delivered messages as a percentage of sent messages.",
    "opened_rate": "Opens as a percentage of delivered messages.",
    "unique_opened_rate": "Unique opens as a percentage of delivered messages.",
    "clicked_rate": "Clicks as a percentage of delivered messages.",
    "unique_clicked_rate": "Unique clicks as a percentage of delivered messages.",
    "unsubscribed_rate": "Unsubscribes as a percentage of delivered messages.",
    "complained_rate": "Spam complaints as a percentage of delivered messages.",
    "bounce_rate": "Bounces as a percentage of processed messages.",
    "permanent_fail_rate": "Permanent failures as a percentage of processed messages.",
    "delayed_rate": "Messages not delivered on the first attempt as a percentage of delivered messages.",
}


def _breakdown_columns(dimension: str, label: str) -> dict[str, str]:
    return {
        **_METRICS_COLUMNS,
        dimension: f"The {label} the metrics are grouped by.",
        f"{dimension}_display_value": f"The {label} in display form.",
    }


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
    "webhook_events": {
        "description": (
            "An event pushed by a Mailgun webhook (accepted, delivered, opened, clicked, failed, "
            "complained, unsubscribed). Same shape as an events row, but kept past Mailgun's "
            "retention window and without a sending domain, which webhook payloads don't carry."
        ),
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/user-manual/events/",
        "columns": {
            "id": "Unique identifier for the event.",
            "event": "The event type (accepted, delivered, opened, clicked, failed, complained, unsubscribed).",
            "timestamp": "Time the event occurred.",
            "recipient": "The recipient email address the event relates to.",
            "recipient-domain": "The domain of the recipient email address.",
            "message": "Details about the message that generated the event.",
            "envelope": "The SMTP envelope the message was sent with.",
            "tags": "The tags associated with the message.",
            "campaigns": "The campaigns associated with the message.",
            "delivery-status": "Delivery status details, including SMTP response codes.",
            "severity": "Severity of a failure event (temporary or permanent).",
            "reason": "The reason a delivery failed, if applicable.",
            "client-info": "The client that generated an open or click (browser, OS, device type).",
            "geolocation": "The approximate location an open or click came from.",
            "url": "The link that was clicked, for click events.",
            "log-level": "Mailgun's log level for the event (info, warn, error).",
            "user-variables": "Custom variables attached to the message when it was sent.",
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
    "metrics": {
        "description": "Daily sending, delivery and engagement metrics for the whole Mailgun account.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _METRICS_COLUMNS,
    },
    "domain_metrics": {
        "description": "Daily sending, delivery and engagement metrics for each sending domain.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _breakdown_columns("domain", "sending domain"),
    },
    "tag_metrics": {
        "description": "Daily sending, delivery and engagement metrics for each message tag.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _breakdown_columns("tag", "message tag"),
    },
    "country_metrics": {
        "description": "Daily engagement metrics for each country, from the IP of the opening or clicking recipient. Non-engagement counts fall under Unknown.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _breakdown_columns("country", "ISO 3166 country code"),
    },
    "recipient_provider_metrics": {
        "description": "Daily sending, delivery and engagement metrics for each recipient mailbox provider, such as Gmail or Outlook 365.",
        "docs_url": _METRICS_DOCS_URL,
        "columns": _breakdown_columns("recipient_provider", "recipient mailbox provider"),
    },
}
