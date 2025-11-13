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

WORKFLOWS = [
    ProcessTaskWorkflow,
]

ACTIVITIES = [
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
