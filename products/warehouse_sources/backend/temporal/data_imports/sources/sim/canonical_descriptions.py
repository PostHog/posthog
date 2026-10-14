from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "Active workspace workflows with deployment state and run counts.",
        "docs_url": "https://docs.sim.ai/api-reference/workflows/listWorkflows",
        "columns": {
            "id": "Unique workflow identifier.",
            "workspaceId": "Workspace that owns the workflow.",
            "name": "Workflow name.",
            "createdAt": "Timestamp when the workflow was created.",
            "updatedAt": "Timestamp when the workflow was last updated.",
            "runCount": "Number of settled runs, including completed, failed, and cancelled runs.",
        },
    },
    "logs": {
        "description": "Workflow execution summaries with status, duration, cost, and output file metadata.",
        "docs_url": "https://docs.sim.ai/api-reference/logs/listLogs",
        "columns": {
            "runId": "Unique run identifier.",
            "workflowId": "Workflow identifier, or null when unavailable.",
            "status": "Current execution status.",
            "startedAt": "Execution start timestamp.",
            "endedAt": "Execution end timestamp, or null while the run is active.",
            "totalDurationMs": "Total execution duration in milliseconds, or null when unavailable.",
            "cost": "Total execution cost in USD, or null when no cost is recorded.",
        },
    },
}
