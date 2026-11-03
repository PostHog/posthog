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
    "schedules": {
        "description": "A schedule in your Temporal namespace that starts workflows on a recurring spec, with its recent and upcoming actions.",
        "docs_url": "https://docs.temporal.io/schedule",
        "columns": {
            "id": "The schedule ID, unique within the namespace.",
            "spec": "When the schedule takes actions: calendar, interval, and cron specifications.",
            "workflow_type": "Name of the workflow type that the schedule starts.",
            "notes": "Human-readable notes about the schedule, such as why it was paused.",
            "paused": "Whether the schedule is paused.",
            "recent_actions": "The most recent actions the schedule took, with the workflow ID and run ID each one started.",
            "future_action_times": "The next times at which the schedule will take an action.",
            "search_attributes": "Indexed key-value attributes used to filter and find schedules.",
        },
    },
    "namespaces": {
        "description": "A namespace on the Temporal cluster, with its retention and archival configuration.",
        "docs_url": "https://docs.temporal.io/namespaces",
        "columns": {
            "id": "Unique identifier of the namespace.",
            "name": "Name of the namespace.",
            "state": "Registration state of the namespace (e.g. NAMESPACE_STATE_REGISTERED, NAMESPACE_STATE_DEPRECATED).",
            "description": "Description of the namespace.",
            "owner_email": "Email address of the namespace owner.",
            "data": "A key-value map for any customized purpose.",
            "capabilities": "All capabilities the namespace supports.",
            "config": "Namespace configuration: workflow execution retention, and history and visibility archival state and URIs.",
            "replication_config": "Replication configuration: the active cluster and the clusters the namespace replicates to.",
            "failover_version": "Failover version of the namespace, used for multi-cluster replication.",
            "is_global_namespace": "Whether the namespace is replicated across clusters.",
        },
    },
    "standalone_activities": {
        "description": "An activity execution started directly by a client rather than by a workflow, with its status and timing.",
        "docs_url": "https://docs.temporal.io/activities",
        "columns": {
            "activity_id": "A unique identifier of this activity within its namespace, together with the run ID.",
            "run_id": "The run ID of the standalone activity.",
            "activity_type": "Name of the activity type, which maps to an activity registered on a worker.",
            "schedule_time": "Time the activity was originally scheduled.",
            "close_time": "Time the activity reached a terminal status, if it has closed.",
            "status": "Execution status. Only the running status and terminal statuses appear in this table.",
            "task_queue": "Task queue the activity was scheduled on.",
            "execution_time": "Time at which the first activity task is made available for dispatch: the schedule time plus the start delay.",
            "execution_duration": "Duration from schedule time to close time, only set when the activity has closed.",
            "state_transition_count": "Number of state transitions of the activity, updated on terminal status.",
            "search_attributes": "Indexed key-value attributes from the start request.",
        },
    },
}
