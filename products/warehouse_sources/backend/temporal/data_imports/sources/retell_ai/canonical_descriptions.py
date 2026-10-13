from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "calls": {
        "description": "Voice call records with status, analysis, latency, and costs. The list endpoint omits transcripts and recording URLs.",
        "docs_url": "https://docs.retellai.com/api-references/list-calls",
        "columns": {
            "call_id": "Unique identifier of the call.",
            "agent_id": "Identifier of the agent handling the call.",
            "start_timestamp": "Call start time, converted from epoch milliseconds to a UTC timestamp.",
            "end_timestamp": "Call end time, converted from epoch milliseconds to a UTC timestamp.",
            "disconnection_reason": "Reason the call disconnected.",
            "call_analysis": "Post-call analysis results.",
            "call_cost": "Call cost breakdown in cents.",
        },
    },
    "agents": {
        "description": "Unique voice and chat agents with names, channels, modification times, and tags.",
        "docs_url": "https://docs.retellai.com/api-references/list-agents",
        "columns": {
            "agent_id": "Unique identifier of the agent.",
            "channel": "Whether the agent handles voice calls or chats.",
            "user_modified_timestamp": "Last user modification time in epoch milliseconds.",
        },
    },
    "chats": {
        "description": "Chat records with status, timing, analysis, and costs.",
        "docs_url": "https://docs.retellai.com/api-references/list-chats",
        "columns": {
            "chat_id": "Unique identifier of the chat.",
            "start_timestamp": "Chat start time, converted from epoch milliseconds to a UTC timestamp.",
            "end_timestamp": "Chat end time, converted from epoch milliseconds to a UTC timestamp.",
        },
    },
    "phone_numbers": {
        "description": "Phone numbers with telephony settings and inbound and outbound agent bindings.",
        "docs_url": "https://docs.retellai.com/api-references/list-phone-numbers",
        "columns": {
            "phone_number": "Unique phone number in E.164 format.",
            "phone_number_type": "Telephony provider or custom phone number type.",
        },
    },
    "voices": {
        "description": "Available voices with providers and voice characteristics.",
        "docs_url": "https://docs.retellai.com/api-references/list-voices",
        "columns": {
            "voice_id": "Unique identifier of the voice.",
            "voice_name": "Name of the voice.",
            "provider": "Provider of the voice.",
        },
    },
}
