"""Canonical, documentation-sourced descriptions for Dropbox endpoints and columns.

Sourced from the official Dropbox HTTP API reference
(https://www.dropbox.com/developers/documentation/http/documentation). Keyed by the endpoint names in
`settings.py` `DROPBOX_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Dropbox table.
Columns absent here fall back to LLM enrichment.

Dropbox tags every union value with a `.tag` key; the transport renames those to `tag` so they are
queryable, which is why `tag` appears as a column below.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "files": {
        "description": "Metadata for one file or folder in the account, listed recursively from the configured folder.",
        "docs_url": "https://www.dropbox.com/developers/documentation/http/documentation#files-list_folder",
        "columns": {
            "tag": "Whether the entry is a file or a folder.",
            "id": "Unique, persistent identifier for the file or folder.",
            "name": "Last component of the path, including the extension.",
            "path_lower": "Lowercased full path in the user's Dropbox, for case-insensitive matching.",
            "path_display": "Cased path for display purposes only.",
            "rev": "Unique identifier for the current revision of the file.",
            "size": "Size of the file in bytes.",
            "client_modified": "Modification time set by the client when the file was added or last edited.",
            "server_modified": "Time the file was last modified on Dropbox.",
            "content_hash": "Dropbox content hash of the file, for comparing contents without downloading.",
            "is_downloadable": "Whether the file can be downloaded directly.",
            "sharing_info": "Sharing information for the file or folder, when it lives in a shared folder.",
            "property_groups": "Custom property groups added to the file by an app.",
            "has_explicit_shared_members": "Whether the file has explicitly shared members.",
            "symlink_info": "Set if this file is a symlink.",
            "export_info": "Export options for files that can only be exported (e.g. Dropbox Paper).",
            "file_lock_info": "Lock information, if the file is locked.",
            "parent_shared_folder_id": "ID of the shared folder that contains the entry, if any.",
        },
    },
    "shared_links": {
        "description": "A shared link created on a file or folder in the account.",
        "docs_url": "https://www.dropbox.com/developers/documentation/http/documentation#sharing-list_shared_links",
        "columns": {
            "tag": "Whether the link points at a file or a folder.",
            "url": "The shared link's URL.",
            "id": "Identifier of the file or folder the link points at.",
            "name": "Name of the linked file or folder.",
            "path_lower": "Lowercased path of the linked file or folder in the user's Dropbox.",
            "link_permissions": "Who can access the link and which actions the caller may take on it.",
            "expires": "Expiry time of the link, if one is set.",
            "client_modified": "Modification time set by the client for the linked file.",
            "server_modified": "Time the linked file was last modified on Dropbox.",
            "rev": "Unique identifier for the current revision of the linked file.",
            "size": "Size of the linked file in bytes.",
            "team_member_info": "Team and member information for the user who created the link.",
        },
    },
    "shared_folders": {
        "description": "A shared folder the account is a member of.",
        "docs_url": "https://www.dropbox.com/developers/documentation/http/documentation#sharing-list_folders",
        "columns": {
            "shared_folder_id": "Unique identifier for the shared folder.",
            "name": "Name of the shared folder.",
            "path_lower": "Lowercased path of the folder in the user's Dropbox, if it is mounted.",
            "access_type": "The caller's access level on the shared folder.",
            "is_inside_team_folder": "Whether the folder is inside a team folder.",
            "is_team_folder": "Whether the folder is a team folder.",
            "policy": "Sharing policies that govern the folder.",
            "owner_team": "The team that owns the folder, if any.",
            "parent_shared_folder_id": "ID of the parent shared folder, if the folder is nested.",
            "time_invited": "Time the caller was invited to the folder.",
            "preview_url": "URL for previewing the folder on the Dropbox website.",
            "permissions": "Actions the caller may take on the shared folder.",
            "link_metadata": "Metadata for the shared link on the folder, if one exists.",
        },
    },
    "team_members": {
        "description": "A member of the Dropbox Business team, with the member profile fields lifted to the row root.",
        "docs_url": "https://www.dropbox.com/developers/documentation/http/teams#team-members-list_v2",
        "columns": {
            "team_member_id": "Unique identifier for the team member.",
            "account_id": "The member's Dropbox account ID, if they have joined the team.",
            "email": "The member's email address.",
            "email_verified": "Whether the member has verified their email address.",
            "status": "Membership status (active, invited, suspended, or removed).",
            "name": "The member's name, including given, surname, familiar, and display forms.",
            "membership_type": "Whether the member occupies a full or a guest licence.",
            "external_id": "External ID the team admin set for the member.",
            "account_external_id": "External ID that a team admin can set on the member's account.",
            "joined_on": "Time the member joined the team.",
            "invited_on": "Time the member was invited to the team.",
            "suspended_on": "Time the member was suspended, if applicable.",
            "groups": "IDs of the groups the member belongs to.",
            "member_folder_id": "ID of the member's root namespace folder.",
            "roles": "Administrator roles granted to the member.",
        },
    },
    "team_events": {
        "description": "An event from the Dropbox Business audit log, covering member, file, sharing, and admin activity.",
        "docs_url": "https://www.dropbox.com/developers/documentation/http/teams#team_log-get_events",
        "columns": {
            "_event_id": "Synthetic identifier PostHog derives from the event body, since Dropbox returns audit events without an id.",
            "timestamp": "Time the event occurred, in UTC.",
            "event_category": "Category the event type belongs to (e.g. sharing, logins, file_operations).",
            "event_type": "The specific type of event that occurred.",
            "details": "Type-specific details of the event.",
            "actor": "Who performed the action (a team member, an app, an admin, or Dropbox itself).",
            "origin": "Where the action was performed from, including host, access method, and geo location.",
            "participants": "Users involved in the event other than the actor.",
            "assets": "Files, folders, links, or other objects the event acted on.",
            "involve_non_team_members": "Whether the event involved users outside the team.",
            "context": "The context the action was performed in (e.g. a specific team member or the team itself).",
        },
    },
}
