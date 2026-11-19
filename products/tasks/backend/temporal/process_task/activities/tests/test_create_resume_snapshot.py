from inspect import unwrap

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.constants import DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH, RESUME_SNAPSHOT_KIND
from products.tasks.backend.exceptions import SnapshotFileLimitExceededError, SnapshotTimeoutError
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.activities.create_resume_snapshot import (
    CreateResumeSnapshotInput,
    create_resume_snapshot,
)


@pytest.mark.django_db
def test_create_directory_resume_snapshot_preserves_pending_delivery(activity_environment, mocker, team) -> None:
    task = Task.objects.create(team=team, title="Checkpoint test")
    run = TaskRun.objects.create(team=team, task=task, state={"snapshot_external_id": "im-previous"})
    pending_state = {
        "pending_user_message": "Run the tests",
        "pending_user_artifact_ids": ["artifact-1"],
        "pending_user_message_id": "message-1",
        "pending_user_message_ts": "1.0",
    }

    def capture_snapshot(path: str) -> str:
        TaskRun.update_state_atomic(str(run.id), updates=pending_state)
        return "im-dir"

    sandbox = mocker.Mock()
    sandbox.is_running.return_value = True
    sandbox.create_directory_snapshot.side_effect = capture_snapshot
    SandboxClass = mocker.Mock()
    SandboxClass.get_by_id.return_value = sandbox

    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.create_resume_snapshot.get_sandbox_class",
        return_value=SandboxClass,
    )
    output = activity_environment.run(
        unwrap(create_resume_snapshot),
        CreateResumeSnapshotInput(sandbox_id="sandbox-1", run_id=str(run.id)),
    )

    sandbox.create_directory_snapshot.assert_called_once_with(DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH)
    sandbox.create_snapshot.assert_not_called()
    run.refresh_from_db()
    assert run.state == {
        **pending_state,
        "snapshot_external_id": "im-dir",
        "snapshot_kind": RESUME_SNAPSHOT_KIND,
        "snapshot_mount_path": DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH,
    }
    assert output.external_id == "im-dir"
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
            CreateResumeSnapshotInput(sandbox_id="sandbox-1", run_id="run-1"),
        )

    update_state.assert_not_called()


def _file_limit_error() -> SnapshotFileLimitExceededError:
    return SnapshotFileLimitExceededError(
        "Directory snapshot exceeds Modal's file-count cap",
        {"sandbox_id": "sandbox-1", "path": DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH},
        cause=RuntimeError("filesystem snapshot contains more than 1000000 files"),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("allow_pruning", [False, True])
def test_directory_file_limit_preserves_state(activity_environment, mocker, tmp_path, allow_pruning: bool) -> None:
    saved_file = tmp_path / ".cache" / "notes.txt"
    saved_file.parent.mkdir()
    saved_file.write_text("Uncommitted task notes")
    sandbox = mocker.Mock()
    sandbox.is_running.return_value = True
    sandbox.create_directory_snapshot.side_effect = _file_limit_error()
    sandbox.prune_snapshot_heavy_dirs.side_effect = lambda path: saved_file.unlink()
    SandboxClass = mocker.Mock()
    SandboxClass.get_by_id.return_value = sandbox

    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.create_resume_snapshot.get_sandbox_class",
        return_value=SandboxClass,
    )
    update_state = mocker.patch.object(TaskRun, "update_state_atomic")

    output = async_to_sync(activity_environment.run)(
        create_resume_snapshot,
        CreateResumeSnapshotInput(sandbox_id="sandbox-1", run_id="run-1", allow_pruning=allow_pruning),
    )

    assert output.external_id is None
    assert output.error is not None
    assert saved_file.read_text() == "Uncommitted task notes"
    update_state.assert_not_called()
