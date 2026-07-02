"""Canonical, documentation-sourced descriptions for Slack endpoints and columns.

Sourced from the official Slack Web API reference (https://api.slack.com/methods). Keyed by the
fixed schema names in `settings.py` `ENDPOINTS` (`$channels` from conversations.list, `$users` from
users.list), which match the `ExternalDataSchema.name` of a synced Slack table. Per-channel message
tables are discovered dynamically (keyed by channel ID) and are not documented here. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "$channels": {
        "description": "A channel (conversation) in the Slack workspace — public, private, DM, or group DM.",
        "docs_url": "https://api.slack.com/methods/conversations.list",
        "columns": {
            "id": "Unique identifier for the channel.",
            "name": "The channel's name, without the leading hash.",
            "is_channel": "Whether the conversation is a public or private channel.",
            "is_private": "Whether the channel is private.",
            "is_archived": "Whether the channel has been archived.",
            "is_general": "Whether the channel is the workspace's default 'general' channel.",
            "is_im": "Whether the conversation is a direct message.",
            "is_mpim": "Whether the conversation is a multi-person direct message.",
            "creator": "User ID of the member who created the channel.",
            "created": "Time at which the channel was created, as a Unix timestamp.",
            "num_members": "Number of members in the channel.",
            "topic": "The channel's topic.",
            "purpose": "The channel's stated purpose.",
        },
    },
    "$users": {
        "description": "A member of the Slack workspace.",
        "docs_url": "https://api.slack.com/methods/users.list",
        "columns": {
            "id": "Unique identifier for the user.",
            "team_id": "ID of the workspace (team) the user belongs to.",
            "name": "The user's username (handle).",
            "real_name": "The user's real name.",
            "profile": "The user's profile, including display name, email, and avatar.",
            "is_admin": "Whether the user is an admin of the workspace.",
            "is_owner": "Whether the user is an owner of the workspace.",
            "is_bot": "Whether the user is a bot.",
            "is_app_user": "Whether the user is an authorized app user.",
            "deleted": "Whether the user account has been deactivated.",
            "is_restricted": "Whether the user is a multi-channel guest.",
            "is_ultra_restricted": "Whether the user is a single-channel guest.",
            "tz": "The user's time zone identifier.",
            "updated": "Time at which the user's profile was last updated, as a Unix timestamp.",
        },
    },
}
