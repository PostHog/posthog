"""Canonical, documentation-sourced descriptions for Attentive webhook event tables and columns.

Sourced from the official Attentive webhooks reference (https://docs.attentive.com/pages/program-setup/webhooks/).
Attentive has no bulk read API, so every table is populated from webhook events; keys match the
webhook-backed schema names in `constants.py` `RESOURCE_TO_ATTENTIVE_EVENT_TYPE`, which match the
`ExternalDataSchema.name` of a synced Attentive table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields present on every stored Attentive webhook row. `event_id` and `created_at` are synthesized
# by PostHog during ingestion; `type` and `timestamp` come from the Attentive webhook payload.
_COMMON_COLUMNS = {
    "event_id": "Stable hash of the webhook payload, synthesized by PostHog to dedupe retried deliveries.",
    "type": "The Attentive webhook event type (e.g. 'sms.subscribed', 'email.opened').",
    "timestamp": "Time at which the event occurred, as a Unix timestamp in milliseconds.",
    "created_at": "Event time in Unix seconds, derived from `timestamp` for datetime partitioning.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sms_subscribed": {
        "description": "A subscriber opting in to receive SMS messages from Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber the event is about, including phone and external identifiers.",
            signUpSourceId="ID of the sign-up unit or source the subscriber opted in through.",
        ),
    },
    "sms_sent": {
        "description": "An SMS message sent to a subscriber by Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber the message was sent to, including phone and external identifiers.",
            message="The message that was sent, including its body and metadata.",
            messageId="Identifier of the sent message.",
        ),
    },
    "sms_message_link_click": {
        "description": "A subscriber clicking a link in an SMS message sent by Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber who clicked the link, including phone and external identifiers.",
            message="The message containing the clicked link.",
            link="The link that was clicked.",
        ),
    },
    "email_subscribed": {
        "description": "A subscriber opting in to receive email from Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber the event is about, including email and external identifiers.",
            signUpSourceId="ID of the sign-up unit or source the subscriber opted in through.",
        ),
    },
    "email_unsubscribed": {
        "description": "A subscriber opting out of receiving email from Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber the event is about, including email and external identifiers.",
        ),
    },
    "email_opened": {
        "description": "A subscriber opening an email sent by Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber who opened the email, including email and external identifiers.",
            message="The email message that was opened.",
        ),
    },
    "email_message_link_click": {
        "description": "A subscriber clicking a link in an email sent by Attentive.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber who clicked the link, including email and external identifiers.",
            message="The email message containing the clicked link.",
            link="The link that was clicked.",
        ),
    },
    "custom_attribute_set": {
        "description": "A custom attribute being set on an Attentive subscriber.",
        "docs_url": "https://docs.attentive.com/pages/program-setup/webhooks/",
        "columns": _columns(
            user="The subscriber the attribute was set on, including external identifiers.",
            properties="The custom attribute key-value pairs that were set.",
        ),
    },
}
