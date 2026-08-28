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
}
