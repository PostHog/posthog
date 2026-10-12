"""Canonical, documentation-sourced descriptions for Mixpanel endpoints and columns.

Sourced from the official Mixpanel API reference (https://developer.mixpanel.com/reference/overview).
Keyed by the endpoint names in `settings.py` `MIXPANEL_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Mixpanel table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "export": {
        "description": "Raw event stream — every tracked event with its properties, exported from Mixpanel.",
        "docs_url": "https://developer.mixpanel.com/reference/raw-event-export",
        "columns": {
            "event": "Name of the event that was tracked.",
            "distinct_id": "Identifier of the user who triggered the event.",
            "time": "Time at which the event occurred, as a Unix timestamp (seconds).",
            "$insert_id": "Unique identifier used by Mixpanel to deduplicate events.",
            "$user_id": "Mixpanel-resolved user id for the event, when identity merge is enabled.",
            "$device_id": "Anonymous device identifier associated with the event.",
            "mp_processing_time_ms": "Time at which Mixpanel processed the event, in milliseconds.",
        },
    },
    "engage": {
        "description": "User profiles — the people in Mixpanel and their current profile properties.",
        "docs_url": "https://developer.mixpanel.com/reference/engage-query",
        "columns": {
            "$distinct_id": "Unique identifier for the user profile.",
            "$properties": "Set of profile properties stored on the user.",
            "$email": "User's email address, if set on the profile.",
            "$name": "User's full name, if set on the profile.",
            "$first_name": "User's first name, if set on the profile.",
            "$last_name": "User's last name, if set on the profile.",
            "$last_seen": "Time the user was last seen, as recorded on the profile.",
            "$city": "City stored on the user profile.",
            "$country_code": "Two-letter country code stored on the user profile.",
        },
    },
    "cohorts": {
        "description": "Saved cohorts — named, reusable groups of users defined in the Mixpanel project.",
        "docs_url": "https://developer.mixpanel.com/reference/cohorts-list",
        "columns": {
            "id": "Unique identifier for the cohort.",
            "name": "The cohort's name.",
            "description": "Description of the cohort.",
            "count": "Number of users currently in the cohort.",
            "is_visible": "Whether the cohort is visible in the Mixpanel UI.",
            "created": "Time at which the cohort was created.",
            "project_id": "Identifier of the Mixpanel project the cohort belongs to.",
        },
    },
    "annotations": {
        "description": "Project annotations — dated notes overlaid on Mixpanel reports to mark events.",
        "docs_url": "https://developer.mixpanel.com/reference/list-all-annotations-for-project",
        "columns": {
            "id": "Unique identifier for the annotation.",
            "date": "Date the annotation applies to.",
            "description": "Text of the annotation.",
            "project_id": "Identifier of the Mixpanel project the annotation belongs to.",
            "user": "User who created the annotation.",
        },
    },
}
