"""Canonical, documentation-sourced descriptions for Gong endpoints and columns.

Sourced from the official Gong API reference (https://gong.app.gong.io/settings/api/documentation).
Keyed by the endpoint names in `settings.py` `GONG_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Gong table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": "A recorded call or meeting captured in Gong.",
        "docs_url": "https://gong.app.gong.io/settings/api/documentation#post-/v2/calls/extensive",
        "columns": {
            "id": "Unique identifier for the call.",
            "title": "Title of the call.",
            "url": "URL of the call within the Gong web app.",
            "started": "Time at which the call started (ISO 8601).",
            "duration": "Duration of the call in seconds.",
            "direction": "Direction of the call (Inbound, Outbound, Conference, or Unknown).",
            "scope": "Whether the call was internal or external.",
            "media": "Media type of the call (Audio or Video).",
            "language": "Detected primary language of the call.",
            "workspaceId": "Identifier of the workspace the call belongs to.",
            "primaryUserId": "Identifier of the main Gong user (host) on the call.",
            "scheduled": "Scheduled start time of the call, if applicable.",
        },
    },
    "users": {
        "description": "A Gong user (team member whose calls and activity are tracked).",
        "docs_url": "https://gong.app.gong.io/settings/api/documentation#get-/v2/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "emailAddress": "The user's primary email address.",
            "firstName": "The user's first name.",
            "lastName": "The user's last name.",
            "active": "Whether the user account is active.",
            "title": "The user's job title.",
            "managerId": "Identifier of the user's manager, if set.",
            "phoneNumber": "The user's phone number.",
            "created": "Time at which the user was created in Gong.",
        },
    },
    "scorecards": {
        "description": "A scorecard template used to evaluate calls in Gong.",
        "docs_url": "https://gong.app.gong.io/settings/api/documentation#get-/v2/settings/scorecards",
        "columns": {
            "scorecardId": "Unique identifier for the scorecard.",
            "scorecardName": "Name of the scorecard.",
            "workspaceId": "Identifier of the workspace the scorecard belongs to.",
            "enabled": "Whether the scorecard is currently enabled.",
            "questions": "The evaluation questions that make up the scorecard.",
            "created": "Time at which the scorecard was created.",
            "updated": "Time at which the scorecard was last updated.",
        },
    },
    "workspaces": {
        "description": "A Gong workspace grouping users, calls, and settings.",
        "docs_url": "https://gong.app.gong.io/settings/api/documentation#get-/v2/workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Name of the workspace.",
            "description": "Description of the workspace.",
        },
    },
}
