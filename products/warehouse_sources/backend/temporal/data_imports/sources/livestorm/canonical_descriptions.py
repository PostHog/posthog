from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_PERSON_COLUMNS = {
    "id": "Unique identifier of the person.",
    "role": "Role of the person: participant or team_member.",
    "email": "Email address of the person.",
    "first_name": "First name of the person.",
    "last_name": "Last name of the person.",
    "timezone": "Timezone of the person.",
    "avatar_link": "URL of the person's avatar.",
    "created_at": "When the person was created, as a Unix timestamp in seconds.",
    "updated_at": "When the person was last updated, as a Unix timestamp in seconds.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Livestorm events. An event is a webinar or meeting series with one or more sessions.",
        "docs_url": "https://developers.livestorm.co/reference/get_events",
        "columns": {
            "id": "Unique identifier of the event.",
            "title": "Title of the event.",
            "slug": "URL slug of the event.",
            "registration_link": "Public registration page of the event.",
            "scheduling_status": "Scheduling status: live, upcoming, on_demand, ended, not_started, draft, cancelled or not_scheduled.",
            "everyone_can_speak": "Whether every participant can speak.",
            "sessions_count": "Number of sessions in the event.",
            "created_at": "When the event was created, as a Unix timestamp in seconds.",
            "updated_at": "When the event was last updated, as a Unix timestamp in seconds.",
        },
    },
    "sessions": {
        "description": "Sessions of every event. A session is one scheduled occurrence of an event.",
        "docs_url": "https://developers.livestorm.co/reference/get_sessions",
        "columns": {
            "id": "Unique identifier of the session.",
            "event_id": "Identifier of the event the session belongs to.",
            "status": "Session status: upcoming, live, on_demand, past, past_not_started, canceled or draft.",
            "name": "Name of the session.",
            "timezone": "Timezone of the session.",
            "room_link": "Link to the session room.",
            "attendees_count": "Number of people who attended the session.",
            "registrants_count": "Number of people who registered for the session.",
            "duration": "Duration of the session in seconds.",
            "estimated_started_at": "Scheduled start, as a Unix timestamp in seconds.",
            "started_at": "Actual start, as a Unix timestamp in seconds.",
            "ended_at": "Actual end, as a Unix timestamp in seconds.",
            "canceled_at": "When the session was canceled, as a Unix timestamp in seconds.",
            "breakout_room_parent_session_id": "Identifier of the parent session when this session is a breakout room.",
            "created_at": "When the session was created, as a Unix timestamp in seconds.",
            "updated_at": "When the session was last updated, as a Unix timestamp in seconds.",
        },
    },
    "people": {
        "description": "Every person in the workspace: team members and participants of any event.",
        "docs_url": "https://developers.livestorm.co/reference/get_people",
        "columns": _PERSON_COLUMNS,
    },
    "session_people": {
        "description": "Registrants and attendees of each session, one row per person and session.",
        "docs_url": "https://developers.livestorm.co/reference/get_sessions-id-people",
        "columns": {
            **_PERSON_COLUMNS,
            "session_id": "Identifier of the session the person registered for.",
            "registrant_detail": "Registration details: event, attendance, replay viewing and the registration form answers.",
            "messages_count": "Number of chat messages the person sent in the session.",
            "questions_count": "Number of questions the person asked in the session.",
            "votes_count": "Number of poll votes the person cast in the session.",
            "up_votes_count": "Number of question upvotes the person gave in the session.",
        },
    },
}
