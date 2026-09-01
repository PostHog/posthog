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
    "articles": {
        "description": (
            "A knowledge base article Decagon's AI agent can answer with, including its full "
            "body content and where it was synced from."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "id": "Unique identifier for the article.",
            "content": "Full body content of the article.",
            "source": "System the article comes from.",
            "url": "URL of the article in its source system.",
            "metadata": "Custom metadata attached to the article.",
            "external_document_id": (
                "Identifier of the article in the system it was synced from. Null for articles "
                "created manually in Decagon."
            ),
            "tags": "Tags applied to the article.",
            "created_at": "Timestamp at which the article was created.",
            "updated_at": "Timestamp at which the article was last updated.",
        },
    },
    "article_usage": {
        "description": (
            "Usage counts per knowledge base article, as returned by Decagon's article usage "
            "endpoint. A point-in-time snapshot bucketed in UTC, replaced on every sync."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
    },
    "tags": {
        "description": (
            "A tag in Decagon's taxonomy, one row per tag across all hierarchies. Resolves the "
            "tag ids embedded in conversation rows to names, parents, and hierarchy positions."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "id": "Unique identifier for the tag.",
            "parent_id": "Identifier of the parent tag. Null for root tags.",
            "name": "Name of the tag.",
            "depth": "Depth of the tag within its hierarchy.",
            "is_frozen": "Whether the tag is frozen against edits.",
            "is_outcome": "Whether the tag represents a conversation outcome.",
            "external_key": "External key assigned to the tag, if any.",
            "tag_hierarchy_id": "Identifier of the hierarchy the tag belongs to.",
            "description": "Description of the tag.",
            "config": "Configuration attached to the tag.",
            "human_count": (
                "Number of conversations tagged by a human, as of the most recent sync. A "
                "point-in-time aggregate, not a historical series."
            ),
            "total_count": (
                "Total number of tagged conversations, as of the most recent sync. A "
                "point-in-time aggregate, not a historical series."
            ),
        },
    },
    "admin_logs": {
        "description": (
            "An entry in Decagon's admin log: a configuration change with who made it, when, "
            "and the before and after state. An immutable audit trail."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "id": "Unique identifier for the log entry.",
            "created_at": "Timestamp at which the change was made.",
            "resource_type": "Type of the resource that was changed.",
            "resource_id": "Identifier of the resource that was changed.",
            "action": "Action performed on the resource.",
            "user_id": "Identifier of the user who made the change.",
            "team_id": "Identifier of the team the change belongs to.",
            "status": "Status of the change.",
            "details_before": "State of the resource before the change, as free-form JSON.",
            "details_after": "State of the resource after the change, as free-form JSON.",
        },
    },
    "team_members": {
        "description": (
            "A member of the Decagon team, one row per user including pending invites. "
            "Resolves the user ids referenced by other Decagon tables to a person."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "id": "Unique identifier for the team member.",
            "email": "Email address of the team member.",
            "access": "Access level of the team member: viewer, QA, or admin.",
        },
    },
    "watchtower_jobs": {
        "description": (
            "A Watchtower QA/evaluation job, including the rubric and configuration needed to "
            "interpret its quality scoring."
        ),
        "docs_url": "https://docs.decagon.ai/api-reference/getting-started",
        "columns": {
            "id": "Unique identifier for the job.",
            "name": "Name of the job.",
            "description": "Description of the job.",
            "rubric": "Rubric the job evaluates against, as free-form JSON.",
            "rubric_type": "Type of the rubric.",
            "prompt": "Prompt the job runs, as free-form JSON.",
            "outputs": "Outputs the job produces, as free-form JSON.",
            "config": "Configuration of the job, as free-form JSON.",
            "created_at": "Timestamp at which the job was created.",
            "updated_at": "Timestamp at which the job was last updated.",
            "last_run_at": "Timestamp at which the job last ran.",
            "status": "Status of the job.",
        },
    },
}
