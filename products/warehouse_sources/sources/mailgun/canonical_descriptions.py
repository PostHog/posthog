"""Canonical, documentation-sourced descriptions for Mailgun endpoints and columns.

Sourced from the official Mailgun API reference (https://documentation.mailgun.com/docs/mailgun/api-reference/).
Keyed by the endpoint names in `settings.py` `MAILGUN_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mailgun table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "allowlist": {
        "description": "An address or domain on a sending domain's allowlist, which Mailgun never adds to the bounce list.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/allowlist/get-v3--domainid--whitelists",
        "columns": {
            "domain": "The sending domain the allowlist entry belongs to.",
            "value": "The allowlisted email address or domain.",
            "type": "Whether the entry is an address or a domain.",
            "reason": "The reason given when the entry was added.",
            "createdAt": "Time the entry was added.",
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
    "mailing_list_members": {
        "description": "A member of a mailing list on the Mailgun account.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/mailing-lists/get-lists-list_address-members-pages",
        "columns": {
            "list_address": "The address of the mailing list the member belongs to.",
            "address": "The member's email address.",
            "name": "The member's display name.",
            "vars": "Custom variables stored on the member.",
            "subscribed": "Whether the member is subscribed to the list.",
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
    "subaccounts": {
        "description": "A subaccount under the Mailgun account, used to separate sending for different teams or customers.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/subaccounts/get-v5-accounts-subaccounts",
        "columns": {
            "id": "Unique identifier for the subaccount.",
            "name": "The name of the subaccount.",
            "status": "Whether the subaccount is open, disabled or closed.",
            "features": "The features enabled on the subaccount.",
            "created_at": "Time the subaccount was created.",
            "updated_at": "Time the subaccount was last updated.",
        },
    },
    "logs": {
        "description": "A message event from the account-wide Logs API, such as an accepted, delivered, failed, opened or clicked message.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/logs/post-v1-analytics-logs",
        "columns": {
            "id": "Unique identifier for the log event.",
            "event": "The type of event, such as accepted, delivered, failed, opened or clicked.",
            "timestamp": "Time the event happened.",
            "domain": "The sending domain the event belongs to.",
            "account": "The account (or subaccount) the event belongs to.",
            "recipient": "The recipient email address.",
            "recipient-domain": "The domain of the recipient email address.",
            "recipient-provider": "The recipient's mailbox provider.",
            "message": "Headers and size of the message the event is about.",
            "delivery-status": "SMTP delivery details for delivered and failed events.",
            "severity": "Whether a failure is temporary or permanent.",
            "reason": "Why a message failed or was suppressed.",
            "tags": "The tags on the message.",
            "user-variables": "Custom variables attached to the message.",
            "geolocation": "Location of the recipient for open and click events.",
            "client-info": "Mail client and device of the recipient for open and click events.",
            "url": "The link the recipient clicked, for click events.",
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
    "usage_metrics": {
        "description": "Daily account usage counts, such as processed messages, email validations, previews and blocklist monitoring checks.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/metrics/post-v1-analytics-usage-metrics",
        "columns": {
            "time": "Start of the UTC day the usage covers.",
            "processed_count": "Messages Mailgun processed.",
            "email_validation_count": "Email address validations run.",
            "email_validation_valid_count": "Email address validations that found a valid address.",
            "email_validation_single_count": "Single email address validations.",
            "email_validation_bulk_count": "Email address validations run in bulk jobs.",
            "email_validation_list_count": "Email address validations run against mailing lists.",
            "email_preview_count": "Email previews run.",
            "email_preview_failed_count": "Email previews that failed.",
            "link_validation_count": "Link validations run.",
            "link_validation_failed_count": "Link validations that failed.",
            "seed_test_count": "Inbox placement seed tests run.",
            "ip_blocklist_monitoring_count": "IP blocklist monitoring checks.",
            "domain_blocklist_monitoring_count": "Domain blocklist monitoring checks.",
        },
    },
    "bounce_classification_metrics": {
        "description": "Daily bounce and delay counts for each sending domain, recipient provider and bounce category, from Mailgun's bounce classification. Days with no bounces or delays have no rows.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/bounce-classification/post-v2-bounce-classification-metrics",
        "columns": {
            "timestamp": "Start of the UTC day the counts cover.",
            "domain_name": "The sending domain.",
            "entity_name": "The recipient provider or spam filter, such as Gmail or Spamcop.",
            "category": "The bounce category, such as BOUNCE, GENERIC, GREYLISTED or ESPBLOCK.",
            "critical_bounce_count": "Critical permanent failures.",
            "non_critical_bounce_count": "Non-critical permanent failures.",
            "critical_delay_count": "Critical temporary failures.",
            "non_critical_delay_count": "Non-critical temporary failures.",
            "classified_failures_count": "Total classified bounces and delays.",
            "delivered_smtp_count": "Messages delivered over SMTP. Empty for spam filters.",
            "critical_bounce_rate": "Critical bounces as a percentage. Empty for spam filters.",
            "non_critical_bounce_rate": "Non-critical bounces as a percentage. Empty for spam filters.",
            "critical_delay_rate": "Critical delays as a percentage. Empty for spam filters.",
            "non_critical_delay_rate": "Non-critical delays as a percentage. Empty for spam filters.",
        },
    },
    "template_versions": {
        "description": "A stored version of a domain template in Mailgun. Each template keeps one active version.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/domain-templates/get-v3--domain-name--templates--template-name--versions",
        "columns": {
            "domain": "The sending domain the template belongs to.",
            "template_name": "The name of the template the version belongs to.",
            "tag": "The version tag, unique within the template.",
            "id": "Unique identifier for the version.",
            "engine": "The rendering engine of the version.",
            "template": "The template content of the version.",
            "mjml": "The MJML source of the version.",
            "comment": "A comment on the version.",
            "active": "Whether this is the active version of the template.",
            "createdAt": "Time the version was created.",
            "headers": "Headers stored with the version.",
        },
    },
    "ips": {
        "description": "A sending IP address on the Mailgun account.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/ips/get-v3-ips",
        "columns": {
            "ip": "The IP address.",
            "dedicated": "Whether the IP is dedicated to the account.",
            "enabled": "Whether the IP is enabled.",
            "is_on_warmup": "Whether the IP is on warmup.",
        },
    },
    "ip_pools": {
        "description": "A dedicated IP pool that groups dedicated IPs for a sending stream.",
        "docs_url": "https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/ip-pools/get-v3-ip-pools",
        "columns": {
            "pool_id": "Unique identifier for the IP pool.",
            "name": "Short name of the IP pool.",
            "description": "Long description of the IP pool.",
            "ips": "The IPs in the pool.",
            "is_linked": "Whether the pool is linked to any domains.",
            "is_inherited": "Whether the pool is inherited.",
            "metadata": "Pool metadata, such as when each IP was linked.",
        },
    },
}
