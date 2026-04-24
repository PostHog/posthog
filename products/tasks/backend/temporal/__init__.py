from .automation import RunTaskAutomationWorkflow, run_task_automation_activity
from .create_snapshot.activities import (
    cleanup_sandbox as snapshot_cleanup_sandbox,
    clone_repository as snapshot_clone_repository,
    create_sandbox as snapshot_create_sandbox,
    create_snapshot as snapshot_create_snapshot,
    get_snapshot_context,
    setup_repository as snapshot_setup_repository,
)
from .create_snapshot.workflow import CreateSnapshotForRepositoryWorkflow
from .process_task.activities import (
    checkout_branch_in_sandbox,
    cleanup_sandbox,
    clone_repository_in_sandbox,
    create_resume_snapshot,
    create_sandbox_for_repository,
    emit_progress_activity,
    execute_task_in_sandbox,
    forward_pending_user_message,
    get_sandbox_for_repository,
    get_task_processing_context,
    inject_fresh_tokens_on_resume,
    post_slack_update,
    prepare_sandbox_for_repository,
    read_sandbox_logs,
    relay_sandbox_events,
    send_followup_to_sandbox,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from .process_task.workflow import ProcessTaskWorkflow
from .slack_relay import PostHogCodeAgentRelayWorkflow, relay_slack_message

WORKFLOWS = [
    ProcessTaskWorkflow,
    CreateSnapshotForRepositoryWorkflow,
    PostHogCodeAgentRelayWorkflow,
    RunTaskAutomationWorkflow,
]

ACTIVITIES = [
    # process_task activities
    get_task_processing_context,
    prepare_sandbox_for_repository,
    create_sandbox_for_repository,
    inject_fresh_tokens_on_resume,
    clone_repository_in_sandbox,
    checkout_branch_in_sandbox,
    get_sandbox_for_repository,
    execute_task_in_sandbox,
    forward_pending_user_message,
    relay_sandbox_events,
    create_resume_snapshot,
    send_followup_to_sandbox,
    start_agent_server,
    read_sandbox_logs,
    cleanup_sandbox,
    emit_progress_activity,
    track_workflow_event,
    post_slack_update,
    update_task_run_status,
    relay_slack_message,
    run_task_automation_activity,
    # create_snapshot activities
    get_snapshot_context,
    snapshot_create_sandbox,
    snapshot_clone_repository,
    snapshot_setup_repository,
    snapshot_create_snapshot,
    snapshot_cleanup_sandbox,
]
