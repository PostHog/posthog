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
    "funnels": {
        "description": "Saved funnels — the funnel reports defined in the Mixpanel project, by id and name.",
        "docs_url": "https://developer.mixpanel.com/reference/funnels-list-saved",
        "columns": {
            "funnel_id": "Unique identifier for the saved funnel.",
            "name": "The funnel's name.",
        },
    },
    "funnel_steps": {
        "description": "Daily conversion for each step of every saved funnel, over the last 90 days.",
        "docs_url": "https://developer.mixpanel.com/reference/funnels-query",
        "columns": {
            "funnel_id": "Identifier of the saved funnel the step belongs to.",
            "funnel_name": "Name of the saved funnel the step belongs to.",
            "date": "Day the funnel conversions are bucketed into, as YYYY-MM-DD.",
            "step_index": "Zero-based position of the step in the funnel.",
            "count": "Number of users who converted through this step.",
            "goal": "Name of the step's event.",
            "event": "Name of the step's event.",
            "step_label": "Display label of the step: the event name or the custom event name.",
            "step_conv_ratio": "Conversion rate from the previous step.",
            "overall_conv_ratio": "Conversion rate from the first step of the funnel.",
            "avg_time": "Mean time to convert from the previous step; null for the first step.",
            "avg_time_from_start": "Mean time to convert from the first step.",
            "custom_event": "True when the step is a custom event.",
            "custom_event_id": "Identifier of the custom event, when the step is a custom event.",
        },
    },
    "retention": {
        "description": (
            "Daily recurring (compounded) retention across all events: for each day's cohort of active users, "
            "how many were active again in each following day."
        ),
        "docs_url": "https://developer.mixpanel.com/reference/retention-query",
        "columns": {
            "date": "Day of the cohort, as YYYY-MM-DD.",
            "interval_index": "Days since the cohort day. Interval 0 covers activity within one day of the first event.",
            "count": "Number of users from the cohort who were active in this interval.",
            "first": "Number of users in the cohort.",
        },
    },
    "lexicon_schemas": {
        "description": "Lexicon data dictionary: the schema Mixpanel holds for each event and profile, with its property definitions.",
        "docs_url": "https://developer.mixpanel.com/reference/list-all-schemas-for-project",
        "columns": {
            "entityType": "Kind of entity the schema describes: event or profile.",
            "name": "Name of the entity, for example the event name.",
            "schemaJson": "Schema of the entity: its description and the type and description of each property.",
        },
    },
    "lookup_tables": {
        "description": "Lookup tables defined in the Mixpanel project, by id and name.",
        "docs_url": "https://developer.mixpanel.com/reference/list-lookup-tables",
        "columns": {
            "id": "Unique identifier (UUID) of the lookup table.",
            "name": "The lookup table's name.",
        },
    },
}
