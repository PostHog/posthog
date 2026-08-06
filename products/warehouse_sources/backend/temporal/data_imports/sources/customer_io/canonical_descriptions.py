"""Canonical, documentation-sourced descriptions for Customer.io endpoints and columns.

Sourced from the official Customer.io App API reference (https://docs.customer.io/api/app/) and the
Reporting Webhooks docs (https://customer.io/docs/journeys/reporting-webhooks/). Keyed by the schema
names in `constants.py` (`CIO_WEBHOOK_SCHEMA_NAMES` and `CIO_API_SCHEMA_NAMES`), which match the
`ExternalDataSchema.name` of a synced Customer.io table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.constants import (
    CUSTOMER_RESOURCE_NAME,
    EMAIL_RESOURCE_NAME,
    IN_APP_RESOURCE_NAME,
    PUSH_RESOURCE_NAME,
    SLACK_RESOURCE_NAME,
    SMS_RESOURCE_NAME,
    WEBHOOK_RESOURCE_NAME,
)

# Fields shared by every reporting-webhook event row (flattened from the webhook payload).
_WEBHOOK_COLUMNS = {
    "event_id": "Unique identifier for the reporting-webhook event.",
    "timestamp": "Time at which the event occurred, as a Unix timestamp.",
    "metric": "The specific metric for the event (e.g. sent, delivered, opened, clicked, bounced).",
    "object_type": "Type of object the event is about (customer, email, push, sms, in_app, slack, webhook).",
    "delivery_id": "Identifier of the message delivery the event relates to.",
    "action_id": "Identifier of the specific action (message) within the campaign or journey that produced the event.",
    "parent_action_id": "Identifier of the parent action in the journey, for actions nested inside another action.",
    "customer_id": "Identifier of the customer the event relates to.",
    "campaign_id": "Identifier of the campaign that triggered the message, if any.",
    "newsletter_id": "Identifier of the newsletter that triggered the message, if any.",
}


def _webhook_columns(**overrides: str) -> dict[str, str]:
    return {**_WEBHOOK_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    # --- Reporting-webhook event tables ---
    CUSTOMER_RESOURCE_NAME: {
        "description": "Customer subscription events delivered via the Customer.io reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(
            email_address="Email address of the customer the subscription event relates to.",
        ),
    },
    EMAIL_RESOURCE_NAME: {
        "description": "Email message activity events (sent, delivered, opened, clicked, bounced, etc.) delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(
            recipient="Email address the message was sent to.",
            subject="Subject line of the email.",
            href="URL that was clicked, for click events.",
        ),
    },
    PUSH_RESOURCE_NAME: {
        "description": "Push notification activity events delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(),
    },
    SMS_RESOURCE_NAME: {
        "description": "SMS message activity events delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(
            recipient="Phone number the SMS was sent to.",
        ),
    },
    IN_APP_RESOURCE_NAME: {
        "description": "In-app message activity events delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(),
    },
    SLACK_RESOURCE_NAME: {
        "description": "Slack message activity events delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(),
    },
    WEBHOOK_RESOURCE_NAME: {
        "description": "Outgoing webhook (reporting) action events delivered via the reporting webhook.",
        "docs_url": "https://customer.io/docs/journeys/reporting-webhooks/",
        "columns": _webhook_columns(),
    },
    # --- App API list endpoints ---
    "broadcasts": {
        "description": "A broadcast — a one-time message sent to a segment or list of recipients.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listBroadcasts",
        "columns": {
            "id": "Unique identifier for the broadcast.",
            "name": "Name of the broadcast.",
            "type": "Type of the broadcast (e.g. email, push).",
            "state": "Current state of the broadcast (e.g. draft, active, stopped).",
            "created": "Time at which the broadcast was created, as a Unix timestamp.",
            "updated": "Time at which the broadcast was last updated, as a Unix timestamp.",
            "active": "Whether the broadcast is currently active.",
        },
    },
    "campaigns": {
        "description": "A campaign — an automated, triggered messaging workflow.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listCampaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "Name of the campaign.",
            "type": "Type of the campaign (e.g. triggered, event).",
            "state": "Current state of the campaign (e.g. draft, running, stopped).",
            "created": "Time at which the campaign was created, as a Unix timestamp.",
            "updated": "Time at which the campaign was last updated, as a Unix timestamp.",
            "active": "Whether the campaign is currently active.",
        },
    },
    "collections": {
        "description": "A collection — structured reference data you can use in message content.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listCollections",
        "columns": {
            "id": "Unique identifier for the collection.",
            "name": "Name of the collection.",
            "created_at": "Time at which the collection was created, as a Unix timestamp.",
            "updated_at": "Time at which the collection was last updated, as a Unix timestamp.",
            "rows": "Number of rows in the collection.",
        },
    },
    "newsletters": {
        "description": "A newsletter — a one-off email sent to a segment of customers.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listNewsletters",
        "columns": {
            "id": "Unique identifier for the newsletter.",
            "name": "Name of the newsletter.",
            "type": "Type of the newsletter.",
            "created": "Time at which the newsletter was created, as a Unix timestamp.",
            "updated": "Time at which the newsletter was last updated, as a Unix timestamp.",
        },
    },
    "object_types": {
        "description": "An object type — a category of non-person objects (e.g. companies, accounts) in the workspace.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listObjectTypes",
        "columns": {
            "id": "Unique identifier for the object type.",
            "name": "Name of the object type.",
        },
    },
    "segments": {
        "description": "A segment — a group of customers defined by attributes or behavior.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listSegments",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "Name of the segment.",
            "description": "Description of the segment.",
            "type": "Type of segment (e.g. dynamic, manual).",
            "created_at": "Time at which the segment was created, as a Unix timestamp.",
            "updated_at": "Time at which the segment was last updated, as a Unix timestamp.",
        },
    },
    "sender_identities": {
        "description": "A sender identity — a configured from-name/address used to send messages.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listSenderIdentities",
        "columns": {
            "id": "Unique identifier for the sender identity.",
            "name": "Display name of the sender.",
            "email": "Email address the sender sends from.",
        },
    },
    "snippets": {
        "description": "A snippet — a reusable block of content for message templates.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listSnippets",
        "columns": {
            "name": "Name of the snippet (its natural key within the workspace).",
            "value": "Content of the snippet.",
        },
    },
    "subscription_topics": {
        "description": "A subscription topic — a category customers can opt in or out of.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listSubscriptionTopics",
        "columns": {
            "id": "Unique identifier for the subscription topic.",
            "name": "Name of the subscription topic.",
            "description": "Description of the subscription topic.",
            "state": "Current state of the subscription topic.",
        },
    },
    "transactional": {
        "description": "A transactional message — a template for one-off, triggered messages such as receipts or password resets.",
        "docs_url": "https://docs.customer.io/api/app/#operation/listTransactional",
        "columns": {
            "id": "Unique identifier for the transactional message.",
            "name": "Name of the transactional message.",
            "description": "Description of the transactional message.",
            "created_at": "Time at which the message was created, as a Unix timestamp.",
            "updated_at": "Time at which the message was last updated, as a Unix timestamp.",
        },
    },
}
