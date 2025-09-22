from .activities import ai_agent_work_activity
from .github_activities import (
    cleanup_repo_activity,
    clone_repo_and_create_branch_activity,
    commit_local_changes_activity,
    create_branch_activity,
    create_pr_activity,
    create_pr_and_update_task_activity,
)
from .workflow_activities import (
    check_temporal_workflow_permissions_activity,
    execute_agent_for_transition_activity,
    get_agent_triggered_transition_activity,
    get_workflow_configuration_activity,
    move_task_to_stage_activity,
    should_trigger_agent_workflow_activity,
    trigger_task_processing_activity,
)
from .workflows import WorkflowAgnosticTaskProcessingWorkflow

WORKFLOWS = [
    WorkflowAgnosticTaskProcessingWorkflow,
]

ACTIVITIES = [
    ai_agent_work_activity,
    # github activities
    clone_repo_and_create_branch_activity,
    cleanup_repo_activity,
    create_branch_activity,
    create_pr_activity,
    create_pr_and_update_task_activity,
    commit_local_changes_activity,
    # workflow activities
    check_temporal_workflow_permissions_activity,
    execute_agent_for_transition_activity,
    get_agent_triggered_transition_activity,
    get_workflow_configuration_activity,
    move_task_to_stage_activity,
    trigger_task_processing_activity,
    should_trigger_agent_workflow_activity,
]
