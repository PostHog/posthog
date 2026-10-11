"""Canonical, documentation-sourced descriptions for monday.com endpoints and columns.

Sourced from the official monday.com GraphQL API reference (https://developer.monday.com/api-reference).
Keyed by the endpoint names in `settings.py` `MONDAY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced monday.com table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
            "enabled": "Whether the user account is enabled.",
            "is_admin": "Whether the user is an admin of the account.",
            "is_guest": "Whether the user is a guest with restricted access.",
            "is_pending": "Whether the user has a pending invitation.",
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
}
