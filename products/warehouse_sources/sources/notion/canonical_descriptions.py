"""Canonical, documentation-sourced descriptions for Notion endpoints and columns.

Sourced from the official Notion API reference (https://developers.notion.com/reference/intro).
Keyed by the endpoint names in `settings.py` `NOTION_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Notion table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Fields shared by most Notion objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "object": "String describing the object's Notion type (e.g. 'page', 'block', 'user').",
    "created_time": "Time at which the object was created, in ISO 8601 format.",
    "last_edited_time": "Time at which the object was last edited, in ISO 8601 format.",
    "created_by": "Reference to the user who created the object.",
    "last_edited_by": "Reference to the user who last edited the object.",
    "archived": "Whether the object has been archived (moved to trash).",
    # API version 2026-03-11 renamed `archived` to `in_trash`; describe both so every version's
    # response is covered (unused keys simply fall through).
    "in_trash": "Whether the object is in the trash (the 2026-03-11 rename of `archived`).",
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
    "permission_groups": {
        "description": "A permission group in the Notion workspace, either admin-managed or SCIM-managed.",
        "docs_url": "https://developers.notion.com/reference/admin/list-permission-groups",
        "columns": {
            "id": "Unique identifier for the group.",
            "object": "Always 'group' for this object.",
            "name": "The name of the group.",
        },
    },
    "permission_group_members": {
        "description": "A direct user membership in a Notion permission group, with the user's role in the group.",
        "docs_url": "https://developers.notion.com/reference/admin/list-permission-group-members",
        "columns": {
            "object": "Always 'group_membership' for this object.",
            "group_id": "Identifier of the permission group. Joins to permission_groups.id.",
            "user_id": "Identifier of the member user. Joins to users.id.",
            "member": "The direct member, with its type (always 'user') and user ID.",
            "role": "The user's role in the group: 'owner' or 'member'.",
        },
    },
    "user_credit_usage": {
        "description": "Notion credit usage and credit limit of each workspace member in the current billing period.",
        "docs_url": "https://developers.notion.com/reference/admin/list-user-credit-usage",
        "columns": {
            "id": "User ID of the workspace member. Joins to users.id.",
            "object": "Always 'user_credit_usage' for this object.",
            "credit_limit": "Effective credit limit for the current billing period, or null when no limit applies.",
            "credits_used": "Notion credits used in the current billing period, including agents the member owns.",
            "credits_used_by_type": "Credits used in the current billing period, split by credit type.",
            "total_credits_used": "All-time Notion credits used by the member across every billing period.",
            "metrics_period_start_ms": "Start of the current billing period, in epoch milliseconds (inclusive).",
            "metrics_period_end_ms": "End of the current billing period, in epoch milliseconds (exclusive).",
        },
    },
    "agent_credit_usage": {
        "description": "Credit usage of each Notion agent, with its credits per monthly billing period. Includes deleted agents that kept their usage.",
        "docs_url": "https://developers.notion.com/reference/admin/get-agents-credit-usage",
        "columns": {
            "id": "Unique identifier for the agent.",
            "object": "Always 'agent_credit_usage' for this object.",
            "name": "Name of the agent.",
            "type": "Kind of agent: 'custom' or 'database_autofill'.",
            "status": "Status of the agent, for example 'active', 'credit_limit' or 'deleted'.",
            "credit_source": "Whose credits the agent spends: its owner's ('owner') or the workspace's ('workspace').",
            "owner_user_id": "User ID of the member who owns the agent, or null when it has no owner.",
            "created_by_id": "User ID of the member who created the agent.",
            "credit_limit": "Credit limit enforced on the agent for its credit source, if any.",
            "runs_completed": "All-time count of finished runs (success or failure) of the agent.",
            "total_credits_used": "All-time premium AI credits used by the agent across every billing period.",
            "last_credit_usage_time": "Time of the agent's most recent credit usage, in epoch milliseconds.",
            "credit_per_billing_period_list": "Credits used by the agent in each monthly billing period, newest first, split by credit type.",
        },
    },
}
