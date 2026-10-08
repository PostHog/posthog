from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "executions": {
        "description": "Workflow executions with their flow, state, and timing details.",
        "docs_url": "https://kestra.io/docs/api-reference/open-source",
        "columns": {
            "id": "Unique execution identifier.",
            "namespace": "Namespace that contains the flow.",
            "flowId": "Identifier of the executed flow.",
            "flowRevision": "Flow revision used for this execution.",
            "state": "Execution state, history, start time, end time, and duration.",
            "start_date": "Execution start time from state.startDate, used for incremental sync.",
            "parentId": "Identifier of the parent execution.",
            "labels": "Labels attached to the execution.",
        },
    },
    "flows": {
        "description": "Workflow definitions with tasks, triggers, and configuration.",
        "docs_url": "https://kestra.io/docs/api-reference/open-source",
        "columns": {
            "id": "Flow identifier within its namespace.",
            "namespace": "Namespace that contains the flow.",
            "revision": "Revision number of the flow definition.",
            "disabled": "Whether the flow prevents new executions and pauses its triggers.",
            "tasks": "Tasks defined by the flow.",
            "triggers": "Trigger definitions for the flow.",
        },
    },
    "triggers": {
        "description": "Trigger definitions and their scheduler state.",
        "docs_url": "https://kestra.io/docs/api-reference/open-source",
        "columns": {
            "namespace": "Namespace that contains the trigger's flow.",
            "flow_id": "Identifier of the flow that owns the trigger.",
            "trigger_id": "Trigger identifier within the flow.",
            "trigger": "Trigger definition, including its plugin type.",
            "state": "Runtime state, evaluation dates, and execution reference for the trigger.",
        },
    },
}
