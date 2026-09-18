"""Canonical, documentation-sourced descriptions for Amplitude endpoints and columns.

Sourced from the official Amplitude HTTP API reference (https://amplitude.com/docs/apis), covering the
Export API (events), the Dashboard REST APIs (cohorts, annotations), and the Taxonomy API (event types,
event properties, user properties, event categories). Keyed by the endpoint names in
`settings.py` `AMPLITUDE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Amplitude
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "A single raw event tracked in Amplitude, exported with its user, device, and event properties.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/export",
        "columns": {
            "uuid": "Unique identifier for the event record.",
            "event_type": "Name of the event (e.g. 'Sign Up', 'Purchase').",
            "event_time": "Time the event occurred on the client, in the project's timezone.",
            "server_upload_time": "Time Amplitude's servers received the event — the cursor used for incremental sync.",
            "client_event_time": "Time the event occurred according to the client's device clock.",
            "user_id": "Your application's identifier for the user, if set.",
            "device_id": "Device-level identifier Amplitude uses to track anonymous users.",
            "amplitude_id": "Amplitude's internal unique identifier for the user.",
            "session_id": "Identifier of the session the event belongs to.",
            "event_id": "Counter that increments for each event the user has sent.",
            "event_properties": "Key-value properties attached to the specific event.",
            "user_properties": "Key-value properties describing the user at event time.",
            "platform": "Platform the event came from (e.g. Web, iOS, Android).",
            "os_name": "Operating system name of the device.",
            "device_type": "Type/model of the device that sent the event.",
            "country": "Country the event was sent from, derived from IP.",
            "city": "City the event was sent from, derived from IP.",
            "app_version": "Version of your application that sent the event.",
            "language": "Language set on the device.",
        },
    },
    "cohorts": {
        "description": "A saved group of users in Amplitude defined by behavioral or property criteria.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/behavioral-cohorts",
        "columns": {
            "id": "Unique identifier for the cohort.",
            "name": "Name of the cohort.",
            "description": "Description of the cohort's definition.",
            "size": "Number of users currently in the cohort.",
            "owners": "Users who own the cohort.",
            "published": "Whether the cohort is published and shared.",
            "archived": "Whether the cohort has been archived.",
            "createdAt": "Time the cohort was created.",
            "lastComputed": "Time the cohort's membership was last computed.",
            "lastMod": "Time the cohort was last modified.",
            "type": "Type of cohort (e.g. dynamic or static).",
        },
    },
    "annotations": {
        "description": "A chart annotation in Amplitude marking a notable date with a label.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/chart-annotations",
        "columns": {
            "id": "Unique identifier for the annotation.",
            "date": "Date the annotation is placed on.",
            "label": "Short label shown for the annotation.",
            "details": "Longer description of the annotation.",
        },
    },
    "event_types": {
        "description": "An event type in the project's tracking plan, naming and describing one kind of tracked event.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/taxonomy",
        "columns": {
            "event_type": "Name of the event as sent by your instrumentation — joins to `event_type` on the events table.",
            "display_name": "Human-readable name shown for the event in the Amplitude UI.",
            "description": "Description of what the event means, from the tracking plan.",
            "category": "Event category the event belongs to, as an object carrying the category name.",
            "is_active": "Whether the event is active in the tracking plan.",
            "is_hidden_from_dropdowns": "Whether the event is hidden from event pickers in the Amplitude UI.",
            "is_hidden_from_persona_results": "Whether the event is excluded from persona results.",
            "is_hidden_from_pathfinder": "Whether the event is excluded from Pathfinder charts.",
            "is_hidden_from_timeline": "Whether the event is excluded from the user timeline.",
            "tags": "Tags applied to the event in the tracking plan.",
            "owner": "User who owns the event definition.",
        },
    },
    "event_properties": {
        "description": "An event property definition from the tracking plan, describing one property carried by an event type.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/taxonomy",
        "columns": {
            "event_type": "Event type the property belongs to — joins to `event_type` on the event_types and events tables.",
            "event_property": "Name of the property as it appears inside the event's `event_properties`.",
            "description": "Description of what the property means, from the tracking plan.",
            "type": "Declared value type of the property (for example string, number, boolean, enum).",
            "regex": "Regular expression the property value must match, if one is set.",
            "enum_values": "Allowed values when the property is declared as an enum.",
            "is_array_type": "Whether the property holds an array of values.",
            "is_required": "Whether the tracking plan requires the property on this event.",
            "is_hidden": "Whether the property is hidden from pickers in the Amplitude UI.",
            "classifications": "Data classification labels applied to the property.",
        },
    },
    "user_properties": {
        "description": "A user property definition from the tracking plan, describing one property carried on users.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/taxonomy",
        "columns": {
            "user_property": "Name of the property as it appears inside an event's `user_properties`. Custom group properties carry a `gp:` prefix.",
            "description": "Description of what the property means, from the tracking plan.",
            "type": "Declared value type of the property (for example string, number, boolean, enum).",
            "regex": "Regular expression the property value must match, if one is set.",
            "enum_values": "Allowed values when the property is declared as an enum.",
            "is_array_type": "Whether the property holds an array of values.",
            "is_hidden": "Whether the property is hidden from pickers in the Amplitude UI.",
            "classifications": "Data classification labels applied to the property.",
            "deleted": "Whether the property has been deleted from the tracking plan.",
        },
    },
    "event_categories": {
        "description": "An event category in the tracking plan, used to group event types.",
        "docs_url": "https://amplitude.com/docs/apis/analytics/taxonomy",
        "columns": {
            "id": "Unique identifier for the category.",
            "name": "Name of the category — matches the category name carried on event types.",
        },
    },
}
