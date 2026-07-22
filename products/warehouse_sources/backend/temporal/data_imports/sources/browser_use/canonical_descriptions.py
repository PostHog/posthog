from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the Browser Use v3 OpenAPI spec
# (https://api.browser-use.com/api/v3/openapi.json). Partial coverage is fine — any column not
# listed here falls back to LLM enrichment.
_DOCS_URL = "https://docs.browser-use.com/api-reference"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sessions": {
        "description": "A hosted agent run on Browser Use Cloud, with its status, model, step count, token usage, and per-run costs.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the agent session.",
            "status": "Current lifecycle status of the agent session.",
            "model": "LLM model the agent used for this session.",
            "title": "Human-readable title of the session.",
            "stepCount": "Number of steps the agent took during the session.",
            "isTaskSuccessful": "Whether the agent reported the task as completed successfully.",
            "profileId": "Identifier of the browser profile used for this session.",
            "workspaceId": "Identifier of the workspace the session belongs to.",
            "totalInputTokens": "Total LLM input tokens consumed by the session.",
            "totalOutputTokens": "Total LLM output tokens produced during the session.",
            "llmCostUsd": "LLM cost for the session, in USD.",
            "proxyCostUsd": "Proxy cost for the session, in USD.",
            "browserCostUsd": "Browser cost for the session, in USD.",
            "totalCostUsd": "Total cost for the session, in USD.",
            "createdAt": "Timestamp when the session was created.",
            "updatedAt": "Timestamp when the session was last updated.",
        },
    },
    "browser_sessions": {
        "description": "A hosted browser instance backing agent runs, with its start/finish timestamps, proxy usage, and costs.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the browser session.",
            "status": "Current status of the browser session.",
            "startedAt": "Timestamp when the browser session started.",
            "finishedAt": "Timestamp when the browser session finished, if it has ended.",
            "timeoutAt": "Timestamp when the browser session will time out.",
            "proxyUsedMb": "Proxy bandwidth consumed by the browser session, in megabytes.",
            "proxyCost": "Proxy cost for the browser session, in USD.",
            "browserCost": "Browser cost for the browser session, in USD.",
            "agentSessionId": "Identifier of the agent session this browser session is attached to.",
        },
    },
    "profiles": {
        "description": "A reusable browser profile that persists cookies and browsing state across agent sessions.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the browser profile.",
            "name": "Name of the profile.",
            "lastUsedAt": "Timestamp when the profile was last used by a session.",
            "cookieDomains": "Domains for which the profile stores cookies.",
            "createdAt": "Timestamp when the profile was created.",
            "updatedAt": "Timestamp when the profile was last updated.",
        },
    },
    "workspaces": {
        "description": "A workspace that groups agent sessions and their associated files.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "Name of the workspace.",
            "createdAt": "Timestamp when the workspace was created.",
            "updatedAt": "Timestamp when the workspace was last updated.",
        },
    },
    "session_messages": {
        "description": "Individual agent steps/messages within a session, in the order they occurred.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the message.",
            "sessionId": "Identifier of the session the message belongs to.",
            "role": "Role that produced the message (e.g. user, assistant).",
            "data": "Message payload content.",
            "type": "Type of the message.",
            "summary": "Short summary of the step.",
            "hidden": "Whether the message is hidden from the default session view.",
            "createdAt": "Timestamp when the message was created.",
        },
    },
}
