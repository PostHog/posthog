"""Canonical, documentation-sourced descriptions for Zoom endpoints and columns.

Sourced from the official Zoom API reference (https://developers.zoom.us/docs/api/). Keyed by the
endpoint names in `settings.py` `ZOOM_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Zoom table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A user in the Zoom account.",
        "docs_url": "https://developers.zoom.us/docs/api/users/#tag/users/GET/users",
        "columns": {
            "id": "Unique identifier of the user.",
            "email": "The user's email address.",
            "first_name": "The user's first name.",
            "last_name": "The user's last name.",
            "display_name": "The user's display name.",
            "type": "The user's plan type (1 = Basic, 2 = Licensed, 4 = No meetings host).",
            "status": "The user's status: active, inactive, or pending.",
            "role_id": "Unique identifier of the role assigned to the user.",
            "pmi": "The user's personal meeting ID.",
            "timezone": "The user's time zone.",
            "dept": "The department the user belongs to.",
            "created_at": "Time the user's account was created.",
            "last_login_time": "Time the user last logged in.",
            "verified": "Whether the user's email address is verified (1) or not (0).",
        },
    },
    "meetings": {
        "description": "A scheduled meeting hosted by a user in the Zoom account.",
        "docs_url": "https://developers.zoom.us/docs/api/meetings/#tag/meetings/GET/users/{userId}/meetings",
        "columns": {
            "id": "Unique numeric identifier of the meeting.",
            "uuid": "Universally unique identifier of the meeting instance.",
            "host_id": "Unique identifier of the user hosting the meeting.",
            "topic": "The meeting's topic.",
            "type": "Meeting type (1 = instant, 2 = scheduled, 3 = recurring no fixed time, 8 = recurring fixed time).",
            "start_time": "The meeting's scheduled start time.",
            "duration": "The meeting's scheduled duration, in minutes.",
            "timezone": "Time zone of the meeting's start time.",
            "agenda": "The meeting's agenda.",
            "join_url": "URL participants use to join the meeting.",
            "created_at": "Time the meeting was created.",
        },
    },
    "webinars": {
        "description": "A scheduled webinar hosted by a user in the Zoom account.",
        "docs_url": "https://developers.zoom.us/docs/api/webinars/#tag/webinars/GET/users/{userId}/webinars",
        "columns": {
            "id": "Unique numeric identifier of the webinar.",
            "uuid": "Universally unique identifier of the webinar instance.",
            "host_id": "Unique identifier of the user hosting the webinar.",
            "topic": "The webinar's topic.",
            "type": "Webinar type (5 = scheduled, 6 = recurring no fixed time, 9 = recurring fixed time).",
            "start_time": "The webinar's scheduled start time.",
            "duration": "The webinar's scheduled duration, in minutes.",
            "timezone": "Time zone of the webinar's start time.",
            "agenda": "The webinar's agenda.",
            "join_url": "URL participants use to join the webinar.",
            "created_at": "Time the webinar was created.",
        },
    },
}
