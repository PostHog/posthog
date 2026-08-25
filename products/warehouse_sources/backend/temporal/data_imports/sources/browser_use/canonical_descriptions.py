from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the Browser Use v3 and v4 OpenAPI specs
# (https://api.browser-use.com/api/v3/openapi.json, https://api.browser-use.com/api/v4/openapi.json).
# Keyed by table name and shared across versions; partial coverage is fine — any column absent from
# a version's response (or not listed here) falls back to LLM enrichment. v4 slimmed `sessions` and
# moved the per-run model/token/cost fields onto the new `runs` table.
_DOCS_URL = "https://docs.browser-use.com/api-reference"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sessions": {
        "description": "A hosted agent session on Browser Use Cloud, with its status, task, and the workspace it belongs to.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the agent session.",
            "sessionId": "Unique identifier for the agent session.",
            "latestRunId": "Identifier of the most recent run within the session.",
            "task": "Natural-language task the agent was asked to perform.",
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
    "runs": {
        "description": "An individual agent run on Browser Use Cloud (v4), with its model, status, result, token usage, and cost.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the run.",
            "sessionId": "Identifier of the session this run belongs to.",
            "workspaceId": "Identifier of the workspace the run belongs to.",
            "task": "Natural-language task the agent was asked to perform.",
            "title": "Human-readable title of the run.",
            "model": "LLM model the agent used for this run.",
            "contextLimit": "Context window size, in tokens, available to the model.",
            "status": "Current lifecycle status of the run.",
            "result": "Final result the agent produced, if the run completed.",
            "error": "Error message if the run failed.",
            "totalInputTokens": "Total LLM input tokens consumed by the run.",
            "totalOutputTokens": "Total LLM output tokens produced during the run.",
            "totalCostUsd": "Total cost for the run, in USD.",
            "createdAt": "Timestamp when the run was created.",
            "updatedAt": "Timestamp when the run was last updated.",
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
