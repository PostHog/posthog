from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "conversations": {
        "description": (
            "A conversation between a user and a Decagon AI agent, including every message, "
            "the customer satisfaction rating, tags, and metadata attached to the conversation."
        ),
        "docs_url": "https://docs.decagon.ai/api/exporting-conversations",
        "columns": {
            "conversation_id": "Unique identifier for the conversation.",
            "user_id": "Identifier of the end user who had the conversation.",
            "created_at": "Timestamp at which the conversation was created.",
            "updated_at": "Timestamp at which the conversation was last updated. Advances whenever the conversation receives new messages.",
            "destination": "Channel the conversation was handled on (e.g. AI).",
            "messages": "All messages in the conversation; each message has text, a role (USER or AI), and a created_at timestamp.",
            "csat_rating": "Customer satisfaction rating the user gave the conversation, if any.",
            "tags": "Tags applied to the conversation; each tag has a name and a level.",
            "metadata": "Custom metadata attached to the conversation (e.g. user attributes).",
        },
    },
    "agent_assist_actions": {
        "description": (
            "An Agent Assist action performed by a human support agent, one row per action. "
            "An append-only event stream used to measure agent adoption of AI assist features."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "created_at": "Timestamp at which the action was performed.",
            "agent_name": "Name of the human support agent who performed the action.",
            "action_name": "Name of the Agent Assist action that was performed.",
            "ticket_id": "Identifier of the support ticket the action relates to.",
            "detail": (
                "Additional detail about the action, including the id of the conversation it "
                "relates to. Present only when detail export is enabled for the team."
            ),
        },
    },
}
