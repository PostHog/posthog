from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "state_machines": {
        "description": "State machines in the configured AWS region.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_ListStateMachines.html",
        "columns": {
            "state_machine_arn": "The Amazon Resource Name (ARN) that identifies the state machine.",
            "name": "The state machine name.",
            "type": "The workflow type: STANDARD or EXPRESS.",
            "creation_date": "The time AWS created the state machine, in UTC.",
        },
    },
    "executions": {
        "description": "Executions of Standard state machines, with status and timing data.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_ListExecutions.html",
        "columns": {
            "execution_arn": "The ARN that identifies the execution.",
            "state_machine_arn": "The ARN of the state machine that ran the execution.",
            "name": "The execution name.",
            "status": "The execution status reported by AWS.",
            "start_date": "The execution start time, in UTC.",
            "stop_date": "The execution completion time, in UTC, when available.",
            "redrive_count": "The number of times AWS restarted the execution through redrive.",
            "redrive_date": "The most recent redrive time, in UTC.",
        },
    },
    "execution_history": {
        "description": "Events from Standard execution histories. Input and output payloads are excluded.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_GetExecutionHistory.html",
        "columns": {
            "execution_arn": "The parent execution ARN. Combine it with id to identify an event across this table.",
            "state_machine_arn": "The ARN of the state machine that ran the parent execution.",
            "id": "The event identifier within its execution.",
            "previous_event_id": "The identifier of the preceding event.",
            "type": "The event type reported by AWS.",
            "timestamp": "The event time, in UTC.",
        },
    },
}
