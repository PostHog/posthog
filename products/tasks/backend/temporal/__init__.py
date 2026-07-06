from .automation import RunTaskAutomationWorkflow, run_task_automation_activity
from .code_workstreams.activities.discover_branch_prs import discover_branch_prs
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
    await_agent_server_ready,
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
    invalidate_resume_snapshot,
    launch_agent_server,
    mark_repo_ready,
    post_slack_update,
    prepare_sandbox_for_repository,
    read_sandbox_logs,
    refresh_sandbox_credentials,
    relay_sandbox_events,
    run_wizard,
    send_followup_to_sandbox,
    start_agent_server,
    track_workflow_event,
    update_task_run_status,
)
from .process_task.activities.feature_flags import is_slack_app_agent_design_enabled_for_task_activity
from .process_task.activities.get_pr_context import get_pr_context
from .process_task.activities.slack_agent_design import (
    append_slack_agent_design_steps,
    start_slack_agent_design_stream,
    stop_slack_agent_design_stream,
)
from .process_task.slack_agent_design_relay import SlackAgentDesignRelayWorkflow
from .process_task.workflow import ProcessTaskWorkflow
from .slack_relay import PostHogCodeAgentRelayWorkflow, relay_slack_message

WORKFLOWS = [
    ProcessTaskWorkflow,
    SlackAgentDesignRelayWorkflow,
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
    invalidate_resume_snapshot,
    refresh_sandbox_credentials,
    clone_repository_in_sandbox,
    checkout_branch_in_sandbox,
    get_sandbox_for_repository,
    execute_task_in_sandbox,
    run_wizard,
    forward_pending_user_message,
    relay_sandbox_events,
    create_resume_snapshot,
    send_followup_to_sandbox,
    start_agent_server,
    launch_agent_server,
    await_agent_server_ready,
    mark_repo_ready,
    read_sandbox_logs,
    cleanup_sandbox,
    emit_progress_activity,
    track_workflow_event,
    post_slack_update,
    update_task_run_status,
    get_pr_context,
    relay_slack_message,
    is_slack_app_agent_design_enabled_for_task_activity,
    start_slack_agent_design_stream,
    append_slack_agent_design_steps,
    stop_slack_agent_design_stream,
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
    discover_branch_prs,
    poll_team_pull_requests,
    rebuild_team_workstreams,
]
