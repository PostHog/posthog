"""Canonical, documentation-sourced descriptions for Notion endpoints and columns.

Sourced from the official Notion API reference (https://developers.notion.com/reference/intro).
Keyed by the endpoint names in `settings.py` `NOTION_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Notion table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Notion objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's Notion type (e.g. 'page', 'block', 'user').",
    "created_time": "Time at which the object was created, in ISO 8601 format.",
    "last_edited_time": "Time at which the object was last edited, in ISO 8601 format.",
    "created_by": "Reference to the user who created the object.",
    "last_edited_by": "Reference to the user who last edited the object.",
    "archived": "Whether the object has been archived (moved to trash).",
    "parent": "Reference to the parent object that contains this one.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pages": {
        "description": "A Notion page — a document of content blocks, optionally with database properties.",
        "docs_url": "https://developers.notion.com/reference/page",
        "columns": _columns(
            properties="Property values of the page (title and any database column values).",
            url="URL of the page in Notion.",
            public_url="Public web URL of the page, if it has been published.",
            icon="The page's icon (emoji or external/file image).",
            cover="The page's cover image.",
            in_trash="Whether the page is in the trash.",
        ),
    },
    "databases": {
        "description": "A Notion database (data source) — a collection of pages with a defined set of properties.",
        "docs_url": "https://developers.notion.com/reference/database",
        "columns": _columns(
            title="Title of the database, as rich text.",
            description="Description of the database, as rich text.",
            properties="Schema of the database's columns and their types.",
            url="URL of the database in Notion.",
            public_url="Public web URL of the database, if it has been published.",
            icon="The database's icon (emoji or external/file image).",
            cover="The database's cover image.",
            is_inline="Whether the database is displayed inline within a page.",
        ),
    },
    "users": {
        "description": "A user or bot in the Notion workspace.",
        "docs_url": "https://developers.notion.com/reference/user",
        "columns": {
            "id": "Unique identifier for the user.",
            "object": "Always 'user' for this object.",
            "type": "Type of user: 'person' or 'bot'.",
            "name": "The user's display name.",
            "avatar_url": "URL of the user's avatar image.",
            "person": "Person details, including email, when the user is a person.",
            "bot": "Bot details when the user is an integration bot.",
        },
    },
    "blocks": {
        "description": "A block of content within a Notion page (paragraph, heading, list item, etc.).",
        "docs_url": "https://developers.notion.com/reference/block",
        "columns": _columns(
            type="Type of the block (e.g. paragraph, heading_1, to_do, child_page).",
            has_children="Whether the block has nested child blocks.",
        ),
    },
    "comments": {
        "description": "A comment left on a Notion page or block.",
        "docs_url": "https://developers.notion.com/reference/comment-object",
        "columns": {
            "id": "Unique identifier for the comment.",
            "object": "Always 'comment' for this object.",
            "parent": "Reference to the page or block the comment is attached to.",
            "discussion_id": "Identifier of the discussion thread the comment belongs to.",
            "rich_text": "Content of the comment, as rich text.",
            "created_time": "Time at which the comment was created, in ISO 8601 format.",
            "last_edited_time": "Time at which the comment was last edited, in ISO 8601 format.",
            "created_by": "Reference to the user who created the comment.",
        },
    },
}
