"""Canonical, documentation-sourced descriptions for Fullstory endpoints and columns.

Sourced from the official Fullstory Server API reference (https://developer.fullstory.com/server/).
Keyed by the endpoint names in `fullstory.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Fullstory table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A tracked end user in Fullstory, identified by your application's user id.",
        "docs_url": "https://developer.fullstory.com/server/v2/users/list-users/",
        "columns": {
            "id": "Fullstory-assigned unique identifier for the user.",
            "uid": "Application-specific user id you set when identifying the user.",
            "display_name": "Human-readable display name for the user.",
            "email": "Email address associated with the user.",
            "properties": "Set of custom key-value attributes attached to the user.",
            "is_being_deleted": "Whether the user is currently queued for deletion.",
            "created": "Time at which the user record was created in Fullstory.",
        },
    },
    "segments": {
        "description": "A saved Fullstory segment: a named set of filters over users and their activity.",
        "docs_url": "https://developer.fullstory.com/server/v1/segments/list-segments/",
        "columns": {
            "id": "Unique identifier for the segment.",
            "name": "Display name of the segment.",
            "creator": "Email of the Fullstory user who created the segment.",
            "created": "Time at which the segment was created. Not present for built-in segments.",
            "url": "Link to the segment in the Fullstory app.",
        },
    },
    "sessions": {
        "description": "A recorded session of an identified user, with a link to its session replay.",
        "docs_url": "https://developer.fullstory.com/server/sessions/list-sessions/",
        "columns": {
            "id": "Fullstory session identifier, formatted as <user_id>:<session_id>.",
            "app_url": "Link to the session replay in the Fullstory app.",
            "created_time": "Time at which the session was created.",
            "user_id": "Fullstory identifier of the user the session belongs to (joins to users.id).",
            "uid": "Application-specific user id of the user the session belongs to (joins to users.uid).",
        },
    },
    "events": {
        "description": "An event captured by Fullstory, from a segment export of the built-in everyone segment.",
        "docs_url": "https://developer.fullstory.com/server/v1/segments/export-fields/",
        "columns": {
            "EventStart": "Time at which the event occurred, in UTC.",
            "EventType": "Type of event that was recorded, such as click or navigate.",
            "EventSubType": "Refinement of the event type, when present.",
            "EventCustomName": "Name of the event when it is a custom analytics event.",
            "EventTargetText": "Text of the event target and its child elements, where applicable.",
            "IndvId": "Identifier of the individual, which combines all users with the same user app key.",
            "UserId": "Identifier of the Fullstory user (device cookie) that performed the event.",
            "SessionId": "Identifier of the session within the user. Combine with UserId to identify a session.",
            "PageId": "Identifier of the page load within the session. Combine with UserId and SessionId.",
        },
    },
}
