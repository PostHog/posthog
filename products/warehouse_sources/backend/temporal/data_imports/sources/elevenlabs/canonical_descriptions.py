from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "history": {
        "description": "Text-to-speech and speech-to-speech generation history. One row per generated audio item.",
        "docs_url": "https://elevenlabs.io/docs/api-reference/history/list",
        "columns": {
            "history_item_id": "Unique identifier for the generated audio item.",
            "request_id": "Identifier of the request that produced this item.",
            "voice_id": "Identifier of the voice used for the generation.",
            "voice_name": "Display name of the voice used for the generation.",
            "model_id": "Identifier of the model used for the generation.",
            "text": "The text that was synthesized into audio.",
            "date_unix": "Creation time of the item, in Unix seconds.",
            "character_count_change_from": "Character quota counter before this generation.",
            "character_count_change_to": "Character quota counter after this generation.",
            "content_type": "MIME type of the generated audio.",
            "state": "Processing state of the history item.",
            "source": "How the item was generated (TTS, STS, or Flows).",
        },
    },
    "conversations": {
        "description": "Conversational AI calls handled by your agents. One row per conversation.",
        "docs_url": "https://elevenlabs.io/docs/api-reference/conversations/list",
        "columns": {
            "conversation_id": "Unique identifier for the conversation.",
            "agent_id": "Identifier of the agent that handled the conversation.",
            "agent_name": "Display name of the agent that handled the conversation.",
            "start_time_unix_secs": "Start time of the call, in Unix seconds.",
            "call_duration_secs": "Duration of the call, in seconds.",
            "message_count": "Number of messages exchanged in the conversation.",
            "status": "Lifecycle status of the conversation (initiated, in-progress, processing, done, failed).",
            "call_successful": "Whether the call was evaluated as successful (success, failure, unknown).",
            "transcript_summary": "Model-generated summary of the conversation transcript.",
            "direction": "Whether the call was inbound or outbound.",
            "sentiment_analysis": "Aggregate sentiment and frustration scores for the conversation.",
        },
    },
    "agents": {
        "description": "Conversational AI agent configurations in your workspace. One row per agent.",
        "docs_url": "https://elevenlabs.io/docs/api-reference/agents/list",
        "columns": {
            "agent_id": "Unique identifier for the agent.",
            "name": "Display name of the agent.",
            "tags": "Tags used to categorize the agent.",
            "created_at_unix_secs": "Creation time of the agent, in Unix seconds.",
            "last_call_time_unix_secs": "Time of the agent's most recent call, in Unix seconds.",
            "access_info": "Ownership and access metadata for the agent.",
        },
    },
    "voices": {
        "description": "Voices available in your workspace, including cloned, generated, and premade voices.",
        "docs_url": "https://elevenlabs.io/docs/api-reference/voices/search",
        "columns": {
            "voice_id": "Unique identifier for the voice.",
            "name": "Display name of the voice.",
            "category": "Voice category (generated, cloned, premade, professional, famous, high_quality).",
            "created_at_unix": "Creation time of the voice, in Unix seconds (may be null for older voices).",
            "labels": "Descriptive labels attached to the voice (accent, age, gender, use case).",
            "description": "Free-text description of the voice.",
        },
    },
}
