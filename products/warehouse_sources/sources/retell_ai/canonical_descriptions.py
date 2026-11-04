from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "agent_versions": {
        "description": "Stored versions of every voice and chat agent, with publish state and version lineage.",
        "docs_url": "https://docs.retellai.com/api-references/list-agent-versions",
        "columns": {
            "agent_id": "Identifier of the agent the version belongs to.",
            "version": "Version number of the agent.",
            "is_published": "Whether the agent version is published.",
            "version_title": "Optional title of the agent version.",
            "version_description": "Optional description of the agent version.",
            "base_version": "Version that this agent version was based on.",
            "last_modification_timestamp": "Last modification time in epoch milliseconds.",
        },
    },
    "test_case_definitions": {
        "description": "Simulation test case definitions for every Retell LLM and conversation flow, with prompts, metrics, and tool mocks.",
        "docs_url": "https://docs.retellai.com/api-references/list-test-case-definitions",
        "columns": {
            "test_case_definition_id": "Unique identifier of the test case definition.",
            "name": "Name of the test case definition.",
            "response_engine": "Retell LLM or conversation flow the test case runs against.",
            "user_prompt": "User prompt to simulate in the test case.",
            "metrics": "Metric names the test case evaluates.",
            "dynamic_variables": "Dynamic variables injected into the response engine.",
            "tool_mocks": "Mock tool calls used during the test.",
            "llm_model": "LLM model used for the simulation.",
            "creation_timestamp": "Creation time in epoch milliseconds.",
            "user_modified_timestamp": "Last modification time in epoch milliseconds.",
        },
    },
}
