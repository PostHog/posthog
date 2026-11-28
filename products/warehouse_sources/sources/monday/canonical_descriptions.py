"""Canonical, documentation-sourced descriptions for monday.com endpoints and columns.

Sourced from the official monday.com GraphQL API reference (https://developer.monday.com/api-reference).
Keyed by the endpoint names in `settings.py` `MONDAY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced monday.com table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "boards": {
        "description": "A monday.com board — a workspace that organizes items into groups and columns.",
        "docs_url": "https://developer.monday.com/api-reference/reference/boards",
        "columns": {
            "id": "Unique identifier for the board.",
            "name": "The board's name.",
            "description": "Description of the board.",
            "state": "State of the board: active, archived, or deleted.",
            "board_kind": "Kind of board: public, private, or share.",
            "board_folder_id": "Identifier of the folder the board lives in, if any.",
            "workspace_id": "Identifier of the workspace the board belongs to.",
            "items_count": "Number of items on the board.",
            "permissions": "Permission level controlling who can view or edit the board.",
            "updated_at": "Time at which the board was last updated.",
        },
    },
    "items": {
        "description": "A monday.com item — a single row on a board, with values across its columns.",
        "docs_url": "https://developer.monday.com/api-reference/reference/items",
        "columns": {
            "id": "Unique identifier for the item.",
            "_board_id": "Identifier of the board the item belongs to.",
            "name": "The item's name.",
            "state": "State of the item: active, archived, or deleted.",
            "group": "The group on the board the item belongs to.",
            "column_values": "Values of the item across the board's columns.",
            "creator_id": "Identifier of the user who created the item.",
            "created_at": "Time at which the item was created.",
            "updated_at": "Time at which the item was last updated.",
        },
    },
    "users": {
        "description": "A member of the monday.com account.",
        "docs_url": "https://developer.monday.com/api-reference/reference/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "kind": "The user's role in the account, such as admin, member, guest, or view_only.",
            "status": "The user's activation status: ACTIVE, INACTIVE, or PENDING.",
            "enabled": "Whether the user account is enabled (API versions before 2026-10).",
            "is_admin": "Whether the user is an admin of the account (API versions before 2026-10).",
            "is_guest": "Whether the user is a guest with restricted access (API versions before 2026-10).",
            "is_pending": "Whether the user has a pending invitation (API versions before 2026-10).",
            "title": "The user's job title.",
            "created_at": "Time at which the user was created.",
        },
    },
    "workspaces": {
        "description": "A monday.com workspace — a container that groups related boards and folders.",
        "docs_url": "https://developer.monday.com/api-reference/reference/workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "The workspace's name.",
            "description": "Description of the workspace.",
            "kind": "Kind of workspace: open or closed.",
            "state": "State of the workspace: active, archived, or deleted.",
            "created_at": "Time at which the workspace was created.",
        },
    },
    "folders": {
        "description": "A folder in a monday.com workspace that organizes boards, dashboards, and docs.",
        "docs_url": "https://developer.monday.com/api-reference/reference/folders",
        "columns": {
            "id": "Unique identifier for the folder. Boards reference it through board_folder_id.",
            "name": "The folder's name.",
            "color": "The folder's color.",
            "created_at": "The folder's creation date.",
            "owner_id": "Identifier of the user who owns the folder.",
            "parent": "The folder's parent folder, if it is a sub-folder.",
            "workspace": "The workspace that contains the folder (null id for the main workspace).",
        },
    },
    "board_columns": {
        "description": "A column on a monday.com board. Resolves the column ids used in each item's column_values.",
        "docs_url": "https://developer.monday.com/api-reference/reference/columns",
        "columns": {
            "id": "The column's identifier, unique within its board.",
            "_board_id": "Identifier of the board the column belongs to.",
            "title": "The column's title.",
            "type": "The column's type, such as status, date, people, or numbers.",
            "description": "The column's description.",
            "archived": "Whether the column is archived.",
            "width": "The column's width in pixels.",
            "settings": "The column's type-specific settings as JSON, such as status labels and colors.",
            "settings_str": "The column's settings as a JSON string (API versions before 2025-10).",
        },
    },
    "board_groups": {
        "description": "A group of items on a monday.com board.",
        "docs_url": "https://developer.monday.com/api-reference/reference/groups",
        "columns": {
            "id": "The group's identifier, unique within its board.",
            "_board_id": "Identifier of the board the group belongs to.",
            "title": "The group's title.",
            "color": "The group's color.",
            "position": "The group's position on the board.",
            "archived": "Whether the group is archived.",
            "deleted": "Whether the group is deleted.",
        },
    },
    "board_activity_logs": {
        "description": "An activity log event on a monday.com board, such as a status change, item move, or assignment.",
        "docs_url": "https://developer.monday.com/api-reference/reference/activity-logs",
        "columns": {
            "id": "Unique identifier for the activity log event.",
            "_board_id": "Identifier of the board the event happened on.",
            "event": "The action that took place.",
            "entity": "The entity the event changed: board or pulse (item).",
            "data": "JSON string with the event details, such as the previous and new column values.",
            "user_id": "Identifier of the user who initiated the event.",
            "account_id": "Identifier of the account that initiated the event.",
            "created_at": "Time at which the event happened.",
        },
    },
    "updates": {
        "description": "An update on a monday.com item — a comment posted in the item's updates section.",
        "docs_url": "https://developer.monday.com/api-reference/reference/updates",
        "columns": {
            "id": "Unique identifier for the update.",
            "item_id": "Identifier of the item the update was posted on.",
            "creator_id": "Identifier of the user who posted the update.",
            "body": "The update's HTML-formatted body.",
            "text_body": "The update's body as plain text.",
            "created_at": "Time at which the update was created.",
            "updated_at": "Time at which the update was last updated.",
            "edited_at": "Time at which the update's body was last edited.",
        },
    },
    "teams": {
        "description": "A team of users in the monday.com account.",
        "docs_url": "https://developer.monday.com/api-reference/reference/teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "The team's name.",
            "picture_url": "URL of the team's picture.",
            "is_guest": "Whether the team is a guest team.",
            "created_at": "Time at which the team was created (API versions from 2026-07).",
            "owner_ids": "Identifiers of the users who own the team.",
            "user_ids": "Identifiers of the users in the team.",
        },
    },
    "tags": {
        "description": "A tag in the monday.com account. Resolves the tag ids stored in tags column values.",
        "docs_url": "https://developer.monday.com/api-reference/reference/tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
            "color": "The tag's color.",
        },
    },
    "board_subscribers": {
        "description": "A user or team subscribed to a monday.com board, with a flag for board owners.",
        "docs_url": "https://developer.monday.com/api-reference/reference/boards",
        "columns": {
            "_board_id": "Identifier of the board.",
            "subscriber_type": "Whether the subscriber is a user or a team.",
            "id": "Identifier of the user or team.",
            "is_owner": "Whether the user or team owns the board.",
        },
    },
}
