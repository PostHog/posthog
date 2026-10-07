from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": (
            "One row for each event on the primary calendar of a connected Google account. "
            "A recurring meeting has one row for each occurrence. Titles and attendees are not synced."
        ),
        "docs_url": "https://developers.google.com/workspace/calendar/api/v3/reference/events",
        "columns": {
            "account_id": "Google account ID of the connected account whose calendar holds the event.",
            "id": "Event ID. It is unique within one account's calendar.",
            "status": "confirmed, tentative or cancelled.",
            "event_type": "default, outOfOffice, focusTime, workingLocation, birthday or fromGmail.",
            "visibility": "default, public, private or confidential.",
            "start_at": "Start of the event. An all-day event starts at midnight UTC.",
            "end_at": "End of the event.",
            "is_all_day": "Whether the event has dates and no times.",
            "duration_minutes": "Minutes between the start and the end.",
            "attendee_count": "Number of attendees on the event. Zero for an event with no guests.",
            "response_status": "Reply of the connected account: accepted, declined, tentative or needsAction.",
            "is_organizer": "Whether the connected account organized the event.",
            "is_recurring": "Whether the event is one occurrence of a recurring event.",
            "has_video_call": "Whether the event has a video call attached.",
            "created_at": "Date and time the event was created.",
            "updated_at": "Date and time the event last changed.",
        },
    },
    "accounts": {
        "description": "One row for each Google account connected to this project for calendar sync.",
        "columns": {
            "account_id": "Google account ID of the connected account.",
            "display_name": "Email address of the Google account.",
            "connected_by_email": "Email of the PostHog user who connected the account.",
            "connected_by_name": "Name of the PostHog user who connected the account.",
            "connected_at": "Date and time the account was first connected.",
        },
    },
}
