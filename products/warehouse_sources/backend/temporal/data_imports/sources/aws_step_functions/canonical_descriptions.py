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
            "state_machine_version_arn": "The ARN of the state machine version that ran the execution, when available.",
            "state_machine_alias_arn": "The ARN of the state machine alias that started the execution, when available.",
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
    "state_machine_versions": {
        "description": "Published versions of each state machine. Join on executions.state_machine_version_arn.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_ListStateMachineVersions.html",
        "columns": {
            "state_machine_version_arn": "The ARN that identifies the state machine version.",
            "state_machine_arn": "The ARN of the state machine that owns the version.",
            "creation_date": "The time AWS created the version, in UTC.",
        },
    },
    "state_machine_aliases": {
        "description": "Aliases of each state machine. Join on executions.state_machine_alias_arn.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_DescribeStateMachineAlias.html",
        "columns": {
            "state_machine_alias_arn": "The ARN that identifies the state machine alias.",
            "state_machine_arn": "The ARN of the state machine that owns the alias.",
            "name": "The alias name.",
            "description": "The alias description.",
            "routing_configuration": "The versions the alias routes executions to, with the percentage weight of each.",
            "creation_date": "The time AWS created the alias, in UTC.",
            "update_date": "The time AWS last updated the alias, in UTC.",
        },
    },
    "activities": {
        "description": "Activities in the configured AWS region. Activity ARNs appear in activity events of execution history.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_ListActivities.html",
        "columns": {
            "activity_arn": "The ARN that identifies the activity.",
            "name": "The activity name.",
            "creation_date": "The time AWS created the activity, in UTC.",
        },
    },
    "map_runs": {
        "description": "Distributed Map runs started by Standard executions, with item and child execution counts.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_DescribeMapRun.html",
        "columns": {
            "map_run_arn": "The ARN that identifies the Map Run.",
            "execution_arn": "The ARN of the execution that started the Map Run.",
            "state_machine_arn": "The ARN of the state machine that ran the parent execution.",
            "status": "The Map Run status reported by AWS.",
            "start_date": "The Map Run start time, in UTC.",
            "stop_date": "The Map Run completion time, in UTC, when available.",
            "max_concurrency": "The maximum number of child executions that can run in parallel.",
            "tolerated_failure_percentage": "The maximum percentage of failed items before the Map Run fails.",
            "tolerated_failure_count": "The maximum number of failed items before the Map Run fails.",
            "item_counts": "Counts of processed items by status, such as succeeded, failed, and pending.",
            "execution_counts": "Counts of child workflow executions by status.",
            "redrive_count": "The number of times AWS redrove the Map Run.",
            "redrive_date": "The most recent redrive time, in UTC.",
        },
    },
    "map_run_executions": {
        "description": "Child workflow executions started by Distributed Map runs, including Express children.",
        "docs_url": "https://docs.aws.amazon.com/step-functions/latest/apireference/API_ListExecutions.html",
        "columns": {
            "execution_arn": "The ARN that identifies the child execution.",
            "map_run_arn": "The ARN of the Map Run that started the child execution.",
            "state_machine_arn": "The ARN of the child workflow state machine.",
            "status": "The child execution status reported by AWS.",
            "start_date": "The child execution start time, in UTC.",
            "stop_date": "The child execution completion time, in UTC, when available.",
            "item_count": "The number of items the child execution processed.",
        },
    },
}
