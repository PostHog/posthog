from .cloud_session.activities import (
    provision_sandbox as cloud_provision_sandbox,
    start_agent_server as cloud_start_agent_server,
)
from .cloud_session.workflow import CloudSessionWorkflow
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
    cleanup_sandbox,
    execute_task_in_sandbox,
    get_sandbox_for_repository,
    get_task_processing_context,
    post_slack_update,
    track_workflow_event,
    update_task_run_status,
)
from .process_task.workflow import ProcessTaskWorkflow

WORKFLOWS = [
    ProcessTaskWorkflow,
    CreateSnapshotForRepositoryWorkflow,
    CloudSessionWorkflow,
]

ACTIVITIES = [
    # process_task activities
    get_task_processing_context,
    get_sandbox_for_repository,
    execute_task_in_sandbox,
    cleanup_sandbox,
    track_workflow_event,
    post_slack_update,
    update_task_run_status,
    # create_snapshot activities
    get_snapshot_context,
    snapshot_create_sandbox,
    snapshot_clone_repository,
    snapshot_setup_repository,
    snapshot_create_snapshot,
    snapshot_cleanup_sandbox,
    # cloud_session activities
    cloud_provision_sandbox,
    cloud_start_agent_server,
]
