from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Occurrences of the configured CleverTap event within the export date range.",
        "docs_url": "https://developer.clevertap.com/docs/get-events-api",
        "columns": {
            "event_name": "The event name selected for this connection.",
            "ts": "Event time in account time, stored as a YYYYMMDDHHMMSS integer.",
            "event_date": "The event date in account time, derived from ts for stable partitioning.",
            "profile": "User identifiers, platform, and profile properties associated with this event.",
            "events": "Event summaries returned by CleverTap for this user.",
            "event_props": "Properties associated with this event occurrence.",
            "session_props": "Session metadata and campaign attribution properties.",
        },
    },
    "profiles": {
        "description": "Profiles of users who performed the configured event within the export date range.",
        "docs_url": "https://developer.clevertap.com/docs/get-user-profiles-api",
        "columns": {
            "identity": "The custom user identifier, when the account has assigned one.",
            "email": "The user email address, when available.",
            "name": "The user name, when available.",
            "profileData": "Custom profile properties and channel subscription preferences.",
            "platformInfo": "Device and platform metadata, including platform object IDs.",
            "events": "Lifetime event counts and the first and last occurrence times for each event.",
        },
    },
}
