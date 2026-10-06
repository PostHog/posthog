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
}
