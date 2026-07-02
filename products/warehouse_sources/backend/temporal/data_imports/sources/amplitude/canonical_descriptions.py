"""Canonical, documentation-sourced descriptions for Amplitude endpoints and columns.

Sourced from the official Amplitude HTTP API reference (https://amplitude.com/docs/apis), covering the
Export API (events) and the Dashboard REST APIs (cohorts, annotations). Keyed by the endpoint names in
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
}
