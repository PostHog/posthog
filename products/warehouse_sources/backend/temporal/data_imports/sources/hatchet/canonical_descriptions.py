"""Canonical, documentation-sourced descriptions for Hatchet endpoints and columns.

Sourced from the Hatchet stable v1 REST API contract
(https://github.com/hatchet-dev/hatchet/tree/main/api-contracts/openapi). Keyed by the endpoint
names in `settings.py` `HATCHET_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
table. The nested `metadata` object is flattened onto each row (`id`, `created_at`, `updated_at`),
so those appear as top-level columns. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# workflow_runs and tasks are both V1TaskSummary rows off the same endpoint (only_tasks toggles
# DAG-level runs vs individual task runs), so they share a column dictionary.
_TASK_SUMMARY_COLUMNS = {
    "id": "Unique identifier for the run.",
    "created_at": "Time at which the run resource was created.",
    "updated_at": "Time at which the run resource was last updated.",
    "displayName": "Human-readable name for the run.",
    "status": "Current run status (QUEUED, RUNNING, COMPLETED, CANCELLED, or FAILED).",
    "type": "Whether the run is a DAG or a single TASK.",
    "workflowId": "Identifier of the workflow this run belongs to.",
    "workflowName": "Name of the workflow this run belongs to.",
    "workflowVersionId": "Identifier of the workflow version that produced this run.",
    "workflowRunExternalId": "External identifier of the parent workflow run.",
    "taskId": "Internal numeric identifier of the task.",
    "taskExternalId": "External identifier of the task.",
    "taskInsertedAt": "Time at which the task was inserted.",
    "actionId": "Identifier of the action executed by the task.",
    "stepId": "Identifier of the step the task corresponds to.",
    "tenantId": "Identifier of the tenant that owns the run.",
    "createdAt": "Time at which the run was created.",
    "startedAt": "Time at which the run started executing.",
    "finishedAt": "Time at which the run finished executing.",
    "duration": "Duration of the run, in milliseconds.",
    "retryCount": "Number of times the task has been retried.",
    "attempt": "The current attempt number.",
    "input": "The input payload the run was invoked with.",
    "output": "The output payload the run produced.",
    "errorMessage": "Error message when the run failed.",
    "additionalMetadata": "Arbitrary key-value metadata attached to the run.",
    "isDurable": "Whether the task is a durable task.",
    "numSpawnedChildren": "Number of child tasks spawned by this run.",
    "parentTaskExternalId": "External identifier of the parent task, if any.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflow_runs": {
        "description": "A workflow (DAG) run or standalone task run in Hatchet, capturing its status, timings, and input/output payloads.",
        "docs_url": "https://docs.hatchet.run/home/runs-and-tasks",
        "columns": _TASK_SUMMARY_COLUMNS,
    },
    "tasks": {
        "description": "An individual task run in Hatchet, including the tasks that make up a DAG workflow run.",
        "docs_url": "https://docs.hatchet.run/home/runs-and-tasks",
        "columns": _TASK_SUMMARY_COLUMNS,
    },
    "events": {
        "description": "An event ingested into the Hatchet tenant. Events can trigger workflow runs.",
        "docs_url": "https://docs.hatchet.run/home/run-on-event",
        "columns": {
            "id": "Unique identifier for the event.",
            "created_at": "Time at which the event was created.",
            "updated_at": "Time at which the event was last updated.",
            "key": "The event key used to match workflows that run on this event.",
            "tenantId": "Identifier of the tenant the event belongs to.",
            "scope": "Scope used to categorize or filter the event.",
            "seenAt": "Time at which the event was seen.",
            "payload": "The event payload.",
            "additionalMetadata": "Arbitrary key-value metadata attached to the event.",
            "workflowRunSummary": "Summary of the workflow runs triggered by this event.",
            "triggeredRuns": "External identifiers of the runs triggered by this event.",
            "triggeringWebhookName": "Name of the webhook that triggered the event, if any.",
        },
    },
    "event_keys": {
        "description": "The distinct event keys seen in the tenant, used to match workflows that run on events.",
        "docs_url": "https://docs.hatchet.run/home/run-on-event",
        "columns": {
            "key": "An event key seen in the tenant.",
        },
    },
}
