from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the public Browserbase API reference (https://docs.browserbase.com/reference/api).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sessions": {
        "description": "A browser session run on Browserbase, including its lifecycle timestamps, "
        "resource usage, and region.",
        "docs_url": "https://docs.browserbase.com/reference/api/list-sessions",
        "columns": {
            "id": "Unique identifier for the session.",
            "createdAt": "Timestamp when the session was created.",
            "updatedAt": "Timestamp when the session was last updated.",
            "startedAt": "Timestamp when the session started running.",
            "endedAt": "Timestamp when the session ended.",
            "expiresAt": "Timestamp when the session is scheduled to expire.",
            "projectId": "Identifier of the project the session belongs to.",
            "status": "Current status of the session (RUNNING, ERROR, TIMED_OUT, or COMPLETED).",
            "proxyBytes": "Number of bytes transferred through the Browserbase proxy during the session.",
            "avgCpuUsage": "Average CPU usage over the session's lifetime.",
            "memoryUsage": "Memory used by the session.",
            "keepAlive": "Whether the session is kept alive after the automation disconnects.",
            "contextId": "Identifier of the context (persisted cookies/cache) attached to the session.",
            "region": "Region the session ran in (for example us-west-2, us-east-1, eu-central-1, ap-southeast-1).",
            "userMetadata": "Arbitrary user-supplied metadata attached to the session.",
        },
    },
    "projects": {
        "description": "A Browserbase project reachable by the connected API key.",
        "docs_url": "https://docs.browserbase.com/reference/api/list-projects",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Human-readable name of the project.",
            "ownerId": "Identifier of the project owner.",
            "createdAt": "Timestamp when the project was created.",
            "updatedAt": "Timestamp when the project was last updated.",
            "defaultTimeout": "Default session timeout, in seconds, for the project.",
            "concurrency": "Maximum number of concurrent sessions allowed for the project.",
        },
    },
    "agents": {
        "description": "A reusable agent definition, referenced by `agentId` to apply a system prompt "
        "to every run that uses it.",
        "docs_url": "https://docs.browserbase.com/reference/api/list-agents",
        "columns": {
            "agentId": "Unique identifier for the agent. Used as `agentId` when creating an agent run.",
            "name": "Human-readable name for the agent.",
            "systemPrompt": "System prompt applied to every run that uses this agent.",
            "resultSchema": "JSON Schema that runs referencing this agent aim to conform their result to.",
            "createdAt": "Timestamp when the agent was created.",
            "updatedAt": "Timestamp when the agent was last updated.",
        },
    },
    "agent_runs": {
        "description": "One execution of an agent against a task, transitioned through its statuses by the runner.",
        "docs_url": "https://docs.browserbase.com/reference/api/list-runs",
        "columns": {
            "runId": "Unique identifier for the run.",
            "agentId": "Identifier of the agent applied to this run. Omitted for ad-hoc runs.",
            "task": "The original task description the run was given.",
            "status": "Current status of the run (PENDING, RUNNING, COMPLETED, FAILED, STOPPED, or TIMED_OUT).",
            "sessionId": "Identifier of the Browserbase session powering this run.",
            "sandboxId": "External sandbox identifier assigned by the runner.",
            "resultSchema": "Per-run JSON Schema override for the result shape.",
            "result": "The agent's structured result, present once the run has finished with output.",
            "cause": "Structured failure code and human-readable detail for a run that did not succeed.",
            "startedAt": "Timestamp when the run started.",
            "endedAt": "Timestamp when the run ended.",
            "createdAt": "Timestamp when the run was created.",
            "updatedAt": "Timestamp when the run was last updated.",
        },
    },
    "project_usage": {
        "description": "Consumption totals for a project, read once per project at sync time.",
        "docs_url": "https://docs.browserbase.com/reference/api/get-project-usage",
        "columns": {
            "projectId": "Identifier of the project the totals were read for.",
            "browserMinutes": "Total browser minutes consumed by the project.",
            "proxyBytes": "Total number of bytes transferred through the Browserbase proxy by the project.",
        },
    },
    "session_logs": {
        "description": "A single Chrome DevTools Protocol message recorded during a browser session.",
        "docs_url": "https://docs.browserbase.com/reference/api/get-session-logs",
        "columns": {
            "sessionId": "Identifier of the session the log line belongs to.",
            "pageId": "Identifier of the page within the session that produced the log line.",
            "method": "Name of the DevTools Protocol method that was called.",
            "timestamp": "Milliseconds since the Unix epoch when the log line was recorded.",
            "frameId": "Identifier of the frame the method ran against.",
            "loaderId": "Identifier of the page load the method ran under.",
            "request": "The outgoing message: its timestamp, params, and raw body.",
            "response": "The returned message: its timestamp, result, and raw body.",
        },
    },
}
