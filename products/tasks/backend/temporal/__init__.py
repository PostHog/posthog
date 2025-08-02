from .workflows import TaskProcessingWorkflow
from .activities import (
    process_task_moved_to_todo_activity,
    update_issue_status_activity,
    ai_agent_work_activity,
    commit_and_push_changes_activity,
    get_task_details_activity,
    create_pull_request_activity,
    update_issue_github_info_activity,
)
from .github_activities import (
    clone_repo_and_create_branch_activity,
    cleanup_repo_activity,
    validate_github_integration_activity,
    create_branch_using_integration_activity,
    create_pr_using_integration_activity,
    commit_changes_using_integration_activity,
)

WORKFLOWS = [
    TaskProcessingWorkflow,
]

ACTIVITIES = [
    process_task_moved_to_todo_activity,
    update_issue_status_activity,
    ai_agent_work_activity,
    commit_and_push_changes_activity,
    get_task_details_activity,
    create_pull_request_activity,
    update_issue_github_info_activity,
    clone_repo_and_create_branch_activity,
    cleanup_repo_activity,
    validate_github_integration_activity,
    create_branch_using_integration_activity,
    create_pr_using_integration_activity,
    commit_changes_using_integration_activity,
]
