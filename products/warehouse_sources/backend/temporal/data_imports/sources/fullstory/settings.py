from datetime import timedelta

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

FULLSTORY_BASE_URL = "https://api.fullstory.com"

ENDPOINTS = ("users", "segments", "sessions", "events")

# Only the segment export takes a time range; the users, segments and sessions listings have no
# server-side filter, so they are full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "events": [
        {
            "label": "EventStart",
            "type": IncrementalFieldType.DateTime,
            "field": "EventStart",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

# Export rows carry no unique event id, so the events table can only append.
APPEND_ONLY_ENDPOINTS = ("events",)

SEGMENTS_PAGE_SIZE = 100

# The built-in segment that matches every user. Fullstory recommends it for bulk event export.
EXPORT_SEGMENT_ID = "everyone"
# The export needs a start time, and a first sync has no watermark to derive one from.
EVENTS_INITIAL_LOOKBACK = timedelta(days=90)
# One export job per window keeps each downloaded file bounded and gives resume a fine grain.
EVENTS_EXPORT_WINDOW = timedelta(days=1)
# Leave recent events out of the export until Fullstory has finished processing them.
EVENTS_EXPORT_END_LAG = timedelta(hours=1)
EXPORT_POLL_INTERVAL_SECONDS = 15
# Caps each poll loop so a stuck job fails as a retryable error instead of hanging the activity.
EXPORT_POLL_MAX_ATTEMPTS = 120
EXPORT_BATCH_SIZE = 5000
REQUEST_TIMEOUT_SECONDS = 120
