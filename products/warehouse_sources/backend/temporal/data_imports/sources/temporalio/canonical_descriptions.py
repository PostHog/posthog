"""Canonical, documentation-sourced descriptions for Temporal.io endpoints and columns.

Sourced from the official Temporal documentation and Python SDK (https://docs.temporal.io,
https://python.temporal.io). Keyed by the resource names in `temporalio.py` `TemporalIOResource`,
which match the `ExternalDataSchema.name` of a synced Temporal table. Columns absent here fall back
to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "A workflow execution in your Temporal namespace, with its type, status, and timing.",
        "docs_url": "https://docs.temporal.io/workflow-execution",
        "columns": {
            "id": "The workflow ID assigned by the client that started the execution.",
            "run_id": "Unique identifier for this specific run of the workflow execution.",
            "workflow_type": "Name of the workflow type (function) that was executed.",
            "task_queue": "Name of the task queue the workflow was dispatched on.",
            "status": "Execution status (e.g. RUNNING, COMPLETED, FAILED, CANCELED, TERMINATED, TIMED_OUT).",
            "start_time": "Time at which the workflow execution started.",
            "close_time": "Time at which the workflow execution closed, if it has closed.",
            "execution_time": "Time at which the workflow is scheduled to start executing.",
            "history_length": "Number of events in the workflow's event history.",
            "parent_id": "Workflow ID of the parent workflow, if this is a child workflow.",
            "parent_run_id": "Run ID of the parent workflow, if this is a child workflow.",
            "search_attributes": "Indexed key-value attributes used to filter and find workflows.",
            "memo": "Non-indexed key-value metadata attached to the workflow.",
        },
    },
    "workflow_histories": {
        "description": "Individual events from the event history of each workflow execution.",
        "docs_url": "https://docs.temporal.io/workflow-execution/event",
        "columns": {
            "id": "Synthetic unique identifier combining workflow id, run id, and event task id.",
            "workflow_id": "The workflow ID this history event belongs to.",
            "run_id": "Run ID of the workflow execution this history event belongs to.",
            "workflow_start_time": "Start time of the parent workflow execution.",
            "workflow_close_time": "Close time of the parent workflow execution, if it has closed.",
            "eventId": "Sequential ID of the event within the workflow's history.",
            "eventTime": "Time at which the event occurred.",
            "eventType": "Type of the history event (e.g. WorkflowExecutionStarted, ActivityTaskCompleted).",
            "taskId": "ID of the task that generated the event.",
            "version": "Version of the event, used for failover and replication.",
        },
    },
}
