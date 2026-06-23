from .automation import RunTaskAutomationWorkflow, run_task_automation_activity
from .code_workstreams.activities.list_active_teams import list_active_code_teams
from .code_workstreams.activities.load_pr_urls import load_team_pr_urls
from .code_workstreams.activities.poll_pull_requests import poll_team_pull_requests
from .code_workstreams.activities.rebuild_workstreams import rebuild_team_workstreams
from .code_workstreams.workflow import EvaluateCodeWorkstreamsWorkflow, EvaluateTeamCodeWorkstreamsWorkflow
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
    refresh_sandbox_credentials,
    relay_sandbox_events,
    send_followup_to_sandbox,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from .process_task.activities.get_pr_context import get_pr_context
from .process_task.workflow import ProcessTaskWorkflow
from .slack_relay import PostHogCodeAgentRelayWorkflow, relay_slack_message

WORKFLOWS = [
    ProcessTaskWorkflow,
    CreateSnapshotForRepositoryWorkflow,
    PostHogCodeAgentRelayWorkflow,
    RunTaskAutomationWorkflow,
    EvaluateCodeWorkstreamsWorkflow,
    EvaluateTeamCodeWorkstreamsWorkflow,
]

ACTIVITIES = [
    # process_task activities
    get_task_processing_context,
    prepare_sandbox_for_repository,
    create_sandbox_for_repository,
    inject_fresh_tokens_on_resume,
    refresh_sandbox_credentials,
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
    get_pr_context,
    relay_slack_message,
    run_task_automation_activity,
    # create_snapshot activities
    get_snapshot_context,
    snapshot_create_sandbox,
    snapshot_clone_repository,
    snapshot_setup_repository,
    snapshot_create_snapshot,
    snapshot_cleanup_sandbox,
    list_active_code_teams,
    load_team_pr_urls,
    poll_team_pull_requests,
    rebuild_team_workstreams,
]
