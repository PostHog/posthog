from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "chats": {
        "description": "Daily AI chat runs for active and archived prompts.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-chats",
        "columns": {
            "id": "The unique chat ID.",
            "date": "The date of the chat run.",
            "prompt": "The prompt ID for this chat.",
            "model_channel": "The AI model channel for this chat.",
            "features": "Features detected in the chat, such as shopping or web search.",
        },
    },
    "prompts": {
        "description": "Active prompts tracked by the project.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-prompts",
        "columns": {
            "id": "The unique prompt ID.",
            "messages": "The text submitted to AI models.",
            "tags": "Tags assigned to the prompt.",
            "topic": "The topic assigned to the prompt.",
            "is_archived": "Whether daily tracking has stopped for this prompt.",
            "created_at": "The date when the prompt was created.",
        },
    },
    "archived_prompts": {
        "description": "Archived prompts that no longer run daily.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-prompts",
        "columns": {
            "id": "The unique prompt ID.",
            "is_archived": "Whether daily tracking has stopped for this prompt.",
        },
    },
    "brands": {
        "description": "The project's tracked brands and competitors.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-brands",
        "columns": {
            "id": "The unique brand ID.",
            "name": "The brand name.",
            "is_own": "Whether the brand belongs to the project owner.",
            "domains": "Domains associated with the brand.",
            "aliases": "Other names used to identify the brand.",
        },
    },
    "topics": {
        "description": "Topics used to organize project prompts.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-topics",
        "columns": {"id": "The unique topic ID.", "name": "The topic name."},
    },
    "tags": {
        "description": "User tags and system tags for project prompts.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-tags",
        "columns": {
            "id": "The unique tag ID.",
            "name": "The tag name.",
            "is_system": "Whether Peec manages this tag.",
            "group": "The tag group, or null for an ungrouped tag.",
        },
    },
    "model_channels": {
        "description": "AI model channels and their active models for the project.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-model-channels",
        "columns": {
            "id": "The stable channel ID.",
            "description": "The channel description.",
            "current_model": "The model active in this channel.",
            "is_active": "Whether this channel is active for the project.",
        },
    },
    "tag_groups": {
        "description": "User-defined tag groups, each with its shared color and tag count.",
        "docs_url": "https://docs.peec.ai/api-reference/project/list-tag-groups",
        "columns": {
            "group": "The tag group name. Matches the group column in tags.",
            "color": "The color shared by every tag in the group.",
            "tag_count": "The number of tags in the group.",
        },
    },
    "actions": {
        "description": "Actions to improve AI visibility, both Peec-generated and customer-written.",
        "docs_url": "https://docs.peec.ai/api-reference/actions/list-actions",
        "columns": {
            "id": "The unique action ID.",
            "type": "The action type, such as a template action, content brief, or SEO issue.",
            "status": "The action status: PENDING, ACCEPTED, REJECTED, or COMPLETED.",
            "title": "What the action asks you to do.",
            "group": "The kind of surface the action lands on.",
            "target": "Whether the action lands on an owned page or an earned third-party page.",
            "platform": "The third-party domain the action targets, or null for own-site actions.",
            "topic_id": "The topic the action relates to.",
            "source": "The page the action targets.",
            "impact": "The expected gain if the action is completed, banded across the project's actions.",
            "created_at": "When the action was created.",
            "status_updated_at": "When the status last changed, or null while still pending.",
            "created_by": "Who wrote the action: peec or customer.",
            "priority": "The priority the customer set, or null if not set.",
            "assignee_user_id": "The project member assigned to the action.",
            "due_on": "The due date in the project's timezone.",
            "tag_ids": "Tags the customer filed the action under.",
        },
    },
}
