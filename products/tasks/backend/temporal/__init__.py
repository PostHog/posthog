from .activities import ai_agent_work_activity
from .github_activities import (
    cleanup_repo_activity,
    clone_repo_and_create_branch_activity,
    commit_local_changes_activity,
    create_branch_activity,
    create_pr_activity,
    create_pr_and_update_task_activity,
)
from .process_task.activities import (
    check_snapshot_exists_for_repository,
    cleanup_personal_api_key,
    cleanup_sandbox,
    clone_repository,
    create_sandbox_from_snapshot,
    create_snapshot,
    execute_task_in_sandbox,
    get_sandbox_for_setup,
    get_task_details,
    inject_github_token,
    inject_personal_api_key,
    setup_repository,
    track_workflow_event,
)
from .process_task.workflow import ProcessTaskWorkflow
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
    ProcessTaskWorkflow,
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
    # process_task activities
    get_task_details,
    check_snapshot_exists_for_repository,
    get_sandbox_for_setup,
    clone_repository,
    inject_github_token,
    inject_personal_api_key,
    setup_repository,
    create_snapshot,
    create_sandbox_from_snapshot,
    execute_task_in_sandbox,
    cleanup_personal_api_key,
    cleanup_sandbox,
    track_workflow_event,
]
