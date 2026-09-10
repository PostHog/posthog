"""Canonical, documentation-sourced descriptions for Freshchat endpoints and columns.

Sourced from the official Freshchat API reference (https://developers.freshchat.com/api/).
Keyed by the endpoint names in `settings.py` `FRESHCHAT_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Freshchat table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "agents": {
        "description": "A team member (agent or admin) in your Freshchat account who handles conversations.",
        "docs_url": "https://developers.freshchat.com/api/#agents",
        "columns": {
            "id": "Unique identifier for the agent.",
            "first_name": "The agent's first name.",
            "last_name": "The agent's last name.",
            "email": "The agent's email address.",
            "avatar": "The agent's profile image.",
            "biography": "The agent's biography.",
            "social_profiles": "The agent's linked social profiles.",
            "groups": "The groups the agent belongs to.",
            "skill_id": "Identifier of the skill assigned to the agent.",
            "role_id": "Identifier of the agent's role.",
            "role_name": "The agent's role name.",
            "license_type": "The type of license assigned to the agent.",
            "availability_status": "Whether the agent is currently available.",
            "is_deactivated": "Whether the agent has been deactivated.",
            "is_deleted": "Whether the agent has been deleted.",
            "freshid_uuid": "The agent's Freshworks organisation identifier.",
        },
    },
    "users": {
        "description": "An end user (contact) who has interacted with your Freshchat messaging.",
        "docs_url": "https://developers.freshchat.com/api/#users",
        "columns": {
            "id": "Unique identifier for the user, auto-generated when the user record is created.",
            "created_time": "Time at which the user record was created.",
            "updated_time": "Time at which the user record was last updated.",
            "email": "The user's email address.",
            "first_name": "The user's first name.",
            "last_name": "The user's last name.",
            "avatar": "The user's profile image.",
            "phone": "The user's phone number.",
            "reference_id": "An external identifier you associate with the user.",
            "restore_id": "Identifier used to restore a user's conversation history across devices.",
            "properties": "Custom user properties defined for your account.",
        },
    },
    "groups": {
        "description": "A group of agents used to route and organise Freshchat conversations.",
        "docs_url": "https://developers.freshchat.com/api/#groups",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "The group's name.",
            "description": "The group's description.",
            "routing_type": "How conversations are routed to agents in the group.",
            "standard_response_ids": "Canned responses associated with the group.",
            "business_calendar_id": "Identifier of the business calendar applied to the group.",
            "sla_policy_ids": "SLA policies associated with the group.",
        },
    },
    "channels": {
        "description": "A topic (channel) that users can start a conversation under.",
        "docs_url": "https://developers.freshchat.com/api/#channels",
        "columns": {
            "id": "Unique identifier for the channel.",
            "name": "The channel's name.",
            "icon": "The channel's icon.",
            "welcome_message": "The message shown to users when they open the channel.",
            "tags": "Tags associated with the channel.",
            "locale": "The channel's language/locale.",
            "enabled": "Whether the channel is enabled.",
            "public": "Whether the channel is publicly visible to users.",
            "updated_time": "Time at which the channel was last updated.",
        },
    },
    "accounts_configuration": {
        "description": "Account-level Freshchat configuration for your app.",
        "docs_url": "https://developers.freshchat.com/api/#accounts",
        "columns": {
            "app_id": "Identifier of the Freshchat app (widget).",
            "account_id": "Identifier of the Freshchat account.",
            "organisation_id": "Identifier of the Freshworks organisation.",
            "plan_type": "The account's Freshchat plan.",
        },
    },
}
