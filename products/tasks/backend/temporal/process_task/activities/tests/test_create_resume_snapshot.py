import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.constants import DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH, SNAPSHOT_KIND_DIRECTORY
from products.tasks.backend.exceptions import SnapshotTimeoutError
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.activities.create_resume_snapshot import (
    CreateResumeSnapshotInput,
    create_resume_snapshot,
)


@pytest.mark.django_db
def test_create_directory_resume_snapshot_uses_tmp_mount_path(activity_environment, mocker) -> None:
    sandbox = mocker.Mock()
    sandbox.is_running.return_value = True
    sandbox.create_directory_snapshot.return_value = "im-dir"
    SandboxClass = mocker.Mock()
    SandboxClass.get_by_id.return_value = sandbox

    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.create_resume_snapshot.get_sandbox_class",
        return_value=SandboxClass,
    )
    update_state = mocker.patch.object(TaskRun, "update_state_atomic")

    output = async_to_sync(activity_environment.run)(
        create_resume_snapshot,
        CreateResumeSnapshotInput(sandbox_id="sandbox-1", run_id="run-1", use_directory_snapshot=True),
    )

    sandbox.create_directory_snapshot.assert_called_once_with(DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH)
    sandbox.create_snapshot.assert_not_called()
    update_state.assert_called_once_with(
        "run-1",
        updates={
            "snapshot_external_id": "im-dir",
            "snapshot_kind": SNAPSHOT_KIND_DIRECTORY,
            "snapshot_mount_path": DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
        },
        remove_keys=["pending_user_message", "pending_user_artifact_ids", "pending_user_message_ts"],
    )
    assert output.external_id == "im-dir"
    assert output.snapshot_kind == SNAPSHOT_KIND_DIRECTORY
    assert output.snapshot_mount_path == DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH


@pytest.mark.django_db
def test_transient_snapshot_error_propagates_so_temporal_retries(activity_environment, mocker) -> None:
    sandbox = mocker.Mock()
    sandbox.is_running.return_value = True
    sandbox.create_directory_snapshot.side_effect = SnapshotTimeoutError(
        "Transient error creating directory snapshot",
        {"sandbox_id": "sandbox-1"},
        cause=TimeoutError("Timeout expired"),
        capture=False,
    )
    SandboxClass = mocker.Mock()
    SandboxClass.get_by_id.return_value = sandbox

    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.create_resume_snapshot.get_sandbox_class",
        return_value=SandboxClass,
    )
    update_state = mocker.patch.object(TaskRun, "update_state_atomic")

    with pytest.raises(SnapshotTimeoutError):
        async_to_sync(activity_environment.run)(
            create_resume_snapshot,
            CreateResumeSnapshotInput(sandbox_id="sandbox-1", run_id="run-1", use_directory_snapshot=True),
        )

    update_state.assert_not_called()
