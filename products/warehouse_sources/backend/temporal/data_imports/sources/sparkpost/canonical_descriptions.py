from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the public SparkPost API documentation. Keyed by the endpoint/schema
# name returned by `get_schemas`. Partial coverage is fine — anything omitted falls back to LLM
# enrichment with the table's `docs_url` and column types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Message events (deliveries, bounces, opens, clicks, etc.) from the SparkPost Events Search API. Retained for 10 days.",
        "docs_url": "https://developers.sparkpost.com/api/events/",
        "columns": {
            "event_id": "Unique identifier for the event.",
            "type": "Event type (e.g. delivery, bounce, open, click, injection, spam_complaint).",
            "timestamp": "ISO 8601 UTC time the event occurred.",
            "message_id": "Unique identifier for the message that generated the event.",
            "transmission_id": "Identifier of the transmission that sent the message.",
            "campaign_id": "Campaign the message was associated with.",
            "rcpt_to": "Recipient email address the message was sent to.",
            "subaccount_id": "Subaccount the message was sent from, if any.",
            "bounce_class": "Numeric classification of a bounce event.",
            "reason": "Human-readable reason returned by the receiving mailbox provider.",
            "ip_address": "Sending IP address used for the message.",
            "sending_ip": "Sending IP address used for the message.",
            "template_id": "Stored template used to generate the message, if any.",
        },
    },
    "suppression_list": {
        "description": "Recipients on the account's suppression list, who are excluded from sends.",
        "docs_url": "https://developers.sparkpost.com/api/suppression-list/",
        "columns": {
            "recipient": "Suppressed recipient email address.",
            "type": "Suppression type: transactional or non_transactional.",
            "source": "How the entry was added (e.g. Bounce Rule, Spam Complaint, Manually Added).",
            "description": "Free-text description of why the recipient was suppressed.",
            "transactional": "Whether the recipient is suppressed for transactional messages.",
            "non_transactional": "Whether the recipient is suppressed for non-transactional messages.",
            "created": "ISO 8601 UTC time the suppression entry was created.",
            "updated": "ISO 8601 UTC time the suppression entry was last updated.",
        },
    },
    "recipient_lists": {
        "description": "Stored recipient lists used to address transmissions.",
        "docs_url": "https://developers.sparkpost.com/api/recipient-lists/",
        "columns": {
            "id": "Unique identifier for the recipient list.",
            "name": "Human-readable name of the recipient list.",
            "description": "Description of the recipient list.",
            "total_accepted_recipients": "Number of recipients in the list.",
        },
    },
    "templates": {
        "description": "Stored message templates.",
        "docs_url": "https://developers.sparkpost.com/api/templates/",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "Human-readable name of the template.",
            "description": "Description of the template.",
            "published": "Whether the template is published (vs draft).",
            "last_update_time": "ISO 8601 UTC time the template was last updated.",
        },
    },
    "sending_domains": {
        "description": "Domains configured for sending mail through SparkPost.",
        "docs_url": "https://developers.sparkpost.com/api/sending-domains/",
        "columns": {
            "domain": "The sending domain.",
            "status": "DKIM, SPF, ownership, and compliance verification status for the domain.",
            "shared_with_subaccounts": "Whether the domain is shared with subaccounts.",
        },
    },
    "subaccounts": {
        "description": "Subaccounts under the primary account.",
        "docs_url": "https://developers.sparkpost.com/api/subaccounts/",
        "columns": {
            "id": "Unique identifier for the subaccount.",
            "name": "Human-readable name of the subaccount.",
            "status": "Subaccount status (active, suspended, terminated).",
            "compliance_status": "Compliance status of the subaccount.",
        },
    },
    "webhooks": {
        "description": "Configured event webhooks that push message events to external endpoints.",
        "docs_url": "https://developers.sparkpost.com/api/webhooks/",
        "columns": {
            "id": "Unique identifier for the webhook.",
            "name": "Human-readable name of the webhook.",
            "target": "Destination URL the webhook posts events to.",
            "events": "Event types the webhook is subscribed to.",
            "active": "Whether the webhook is currently active.",
        },
    },
}
