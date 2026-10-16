from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "robots": {
        "description": "Trained robots that extract website data or monitor pages for changes.",
        "docs_url": "https://docs.browse.ai/api",
        "columns": {
            "id": "Robot identifier.",
            "name": "Robot name.",
            "createdAt": "When the robot was created, converted from Unix milliseconds to UTC.",
            "inputParameters": "Inputs accepted by the robot when starting a task.",
        },
    },
    "tasks": {
        "description": "Robot executions with their status and captured data. Large results can be represented by temporary download links.",
        "docs_url": "https://docs.browse.ai/api",
        "columns": {
            "id": "Task identifier.",
            "robotId": "Robot that executed the task.",
            "createdAt": "When the task was created, converted from Unix milliseconds to UTC.",
            "finishedAt": "Task completion time in Unix milliseconds, or null while running.",
            "status": "Whether the task succeeded, failed, or is still running.",
            "capturedTexts": "Named text values extracted by the robot.",
            "capturedLists": "Named lists of rows extracted by the robot.",
            "capturedScreenshots": "Screenshots captured during the task.",
            "capturedDataTemporaryUrl": "Expiring download link used when captured data exceeds 100 KB.",
            "robotBulkRunId": "Bulk run that started the task, when applicable.",
            "runByTaskMonitorId": "Monitor that started the task, when applicable.",
        },
    },
    "monitors": {
        "description": "Scheduled robot runs with their inputs, notification settings, and active or paused status.",
        "docs_url": "https://docs.browse.ai/api",
        "columns": {
            "id": "Monitor identifier.",
            "robotId": "Robot whose monitor list contains this row.",
            "createdAt": "When the monitor was created, converted from Unix milliseconds to UTC.",
            "status": "Whether the monitor is active or paused.",
            "pausedReason": "Reason the monitor was paused.",
            "inputParameters": "Inputs supplied to scheduled runs.",
        },
    },
    "bulk_runs": {
        "description": "Groups of tasks started together with execution status and success and failure counts.",
        "docs_url": "https://docs.browse.ai/api",
        "columns": {
            "id": "Bulk run identifier.",
            "robotId": "Robot used for the bulk run.",
            "createdAt": "When the bulk run was created, converted from Unix milliseconds to UTC.",
            "tasksCount": "Number of tasks in the bulk run.",
            "successfulTasks": "Number of tasks that succeeded.",
            "failedTasks": "Number of tasks that failed.",
        },
    },
}
