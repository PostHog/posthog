"""Canonical, documentation-sourced descriptions for Drip endpoints and columns.

Sourced from the official Drip REST API reference (https://developer.drip.com/). Keyed by the
endpoint names in `settings.py` `DRIP_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Drip table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "subscribers": {
        "description": "A person on a Drip account's email list, with their contact details and engagement state.",
        "docs_url": "https://developer.drip.com/#subscribers",
        "columns": {
            "id": "Unique identifier for the subscriber.",
            "status": "Subscription status (e.g. active, unsubscribed).",
            "email": "The subscriber's email address.",
            "first_name": "The subscriber's first name.",
            "last_name": "The subscriber's last name.",
            "time_zone": "The subscriber's time zone.",
            "ip_address": "IP address recorded for the subscriber.",
            "user_agent": "User agent string recorded for the subscriber.",
            "lifetime_value": "Total revenue attributed to the subscriber, in cents.",
            "custom_fields": "Custom field key-value pairs set on the subscriber.",
            "tags": "List of tags applied to the subscriber.",
            "created_at": "Time at which the subscriber was created.",
            "updated_at": "Time at which the subscriber was last updated.",
        },
    },
    "campaigns": {
        "description": "An email series (drip campaign) that subscribers are enrolled into.",
        "docs_url": "https://developer.drip.com/#campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "status": "Campaign status (e.g. active, paused, draft).",
            "from_name": "Sender name used on the campaign's emails.",
            "from_email": "Sender email address used on the campaign's emails.",
            "subscriber_count": "Number of subscribers currently in the campaign.",
            "created_at": "Time at which the campaign was created.",
        },
    },
    "broadcasts": {
        "description": "A one-time email blast sent to a segment of subscribers.",
        "docs_url": "https://developer.drip.com/#broadcasts",
        "columns": {
            "id": "Unique identifier for the broadcast.",
            "name": "The broadcast's name.",
            "status": "Broadcast status (e.g. draft, scheduled, sent).",
            "subject": "Subject line of the broadcast email.",
            "from_name": "Sender name used on the broadcast.",
            "from_email": "Sender email address used on the broadcast.",
            "send_at": "Time the broadcast is scheduled to send or was sent.",
            "created_at": "Time at which the broadcast was created.",
        },
    },
    "workflows": {
        "description": "An automation workflow that moves subscribers through a series of triggers and actions.",
        "docs_url": "https://developer.drip.com/#workflows",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "name": "The workflow's name.",
            "state": "Workflow state (e.g. active, paused, draft).",
            "created_at": "Time at which the workflow was created.",
        },
    },
    "forms": {
        "description": "A signup form used to capture new subscribers into the account.",
        "docs_url": "https://developer.drip.com/#forms",
        "columns": {
            "id": "Unique identifier for the form.",
            "name": "The form's name.",
            "status": "Form status (e.g. active, inactive).",
            "submission_count": "Number of submissions the form has received.",
            "conversion_count": "Number of submissions that converted to subscribers.",
            "created_at": "Time at which the form was created.",
        },
    },
    "goals": {
        "description": "A conversion goal that tracks when subscribers complete a defined action.",
        "docs_url": "https://developer.drip.com/#goals",
        "columns": {
            "id": "Unique identifier for the goal.",
            "name": "The goal's name.",
            "status": "Goal status (e.g. active, inactive).",
            "created_at": "Time at which the goal was created.",
        },
    },
}
