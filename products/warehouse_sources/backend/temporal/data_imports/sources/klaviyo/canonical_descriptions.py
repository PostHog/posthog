"""Canonical, documentation-sourced descriptions for Klaviyo endpoints and columns.

Sourced from the official Klaviyo API reference (https://developers.klaviyo.com/en/reference/api_overview).
Keyed by the endpoint names in `settings.py` `KLAVIYO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Klaviyo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Klaviyo's JSON:API responses flatten the nested `attributes` object onto each row, so attribute
# fields (name, status, created, updated, ...) appear as top-level columns.
_CAMPAIGN_COLUMNS = {
    "id": "Unique identifier for the campaign.",
    "name": "The campaign's name.",
    "status": "Current status of the campaign (e.g. Draft, Queued without Recipients, Sent).",
    "archived": "Whether the campaign has been archived.",
    "channel": "The channel the campaign sends through (email or sms).",
    "audiences": "The lists and segments the campaign is sent to and excluded from.",
    "send_options": "Options controlling how the campaign is sent.",
    "tracking_options": "Tracking options for opens, clicks, and UTM parameters.",
    "send_strategy": "The strategy used to schedule and send the campaign.",
    "created_at": "Time at which the campaign was created.",
    "updated_at": "Time at which the campaign was last updated.",
    "scheduled_at": "Time at which the campaign is scheduled to send.",
    "send_time": "Time at which the campaign was sent.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "email_campaigns": {
        "description": "An email marketing campaign in Klaviyo sent to a target audience.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_campaigns",
        "columns": _CAMPAIGN_COLUMNS,
    },
    "sms_campaigns": {
        "description": "An SMS marketing campaign in Klaviyo sent to a target audience.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_campaigns",
        "columns": _CAMPAIGN_COLUMNS,
    },
    "events": {
        "description": "An event in Klaviyo recording a profile's action, such as a placed order or opened email.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_events",
        "columns": {
            "id": "Unique identifier for the event.",
            "datetime": "Time at which the event occurred.",
            "timestamp": "Unix timestamp at which the event occurred.",
            "event_properties": "Properties attached to the event.",
            "uuid": "Universally unique identifier for the event.",
            "metric": "The metric this event is an occurrence of (related resource).",
            "profile": "The profile that performed the event (related resource).",
        },
    },
    "flows": {
        "description": "An automated flow in Klaviyo that sends messages based on triggers and conditions.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_flows",
        "columns": {
            "id": "Unique identifier for the flow.",
            "name": "The flow's name.",
            "status": "Current status of the flow (e.g. draft, manual, live).",
            "archived": "Whether the flow has been archived.",
            "trigger_type": "The type of trigger that starts the flow.",
            "created": "Time at which the flow was created.",
            "updated": "Time at which the flow was last updated.",
        },
    },
    "lists": {
        "description": "A list of profiles in Klaviyo used to target campaigns and flows.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_lists",
        "columns": {
            "id": "Unique identifier for the list.",
            "name": "The list's name.",
            "opt_in_process": "The opt-in process for the list (single or double opt-in).",
            "created": "Time at which the list was created.",
            "updated": "Time at which the list was last updated.",
        },
    },
    "metrics": {
        "description": "A metric in Klaviyo that defines a type of tracked event (e.g. Placed Order, Opened Email).",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_metrics",
        "columns": {
            "id": "Unique identifier for the metric.",
            "name": "The metric's name.",
            "integration": "The integration that reports this metric.",
            "created": "Time at which the metric was created.",
            "updated": "Time at which the metric was last updated.",
        },
    },
    "profiles": {
        "description": "A profile in Klaviyo representing a person you can message and track.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_profiles",
        "columns": {
            "id": "Unique identifier for the profile.",
            "email": "The profile's email address.",
            "phone_number": "The profile's phone number.",
            "external_id": "The external identifier you assigned to the profile.",
            "first_name": "The profile's first name.",
            "last_name": "The profile's last name.",
            "organization": "The organization the profile is associated with.",
            "title": "The profile's job title.",
            "location": "The profile's location details.",
            "properties": "Custom properties set on the profile.",
            "created": "Time at which the profile was created.",
            "updated": "Time at which the profile was last updated.",
            "last_event_date": "Time of the profile's most recent event.",
        },
    },
    "list_profiles": {
        "description": "A flat join table mapping which profiles belong to which Klaviyo list.",
        "docs_url": "https://developers.klaviyo.com/en/reference/get_list_relationships_profiles",
        "columns": {
            "list_id": "Identifier of the list.",
            "profile_id": "Identifier of a profile that is a member of the list.",
        },
    },
}
