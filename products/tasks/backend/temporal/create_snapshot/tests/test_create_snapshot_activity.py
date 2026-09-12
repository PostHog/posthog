import uuid

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.constants import SNAPSHOT_KIND_FILESYSTEM
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.create_snapshot.activities.create_snapshot import (
    CreateSnapshotInput,
    create_snapshot,
)
from products.tasks.backend.temporal.create_snapshot.activities.get_snapshot_context import SnapshotContext


def _context(github_integration_id: int, sandbox_backend: str = "hogland") -> SnapshotContext:
    return SnapshotContext(
        github_integration_id=github_integration_id,
        repository="PostHog/posthog",
        team_id=1,
        sandbox_backend=sandbox_backend,
    )


def _mock_sandbox(mocker, snapshot_external_id: str):
    sandbox = mocker.Mock()
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
    sandbox.create_snapshot.return_value = snapshot_external_id
    SandboxClass = mocker.Mock()
    SandboxClass.get_by_id.return_value = sandbox
    mocker.patch(
        "products.tasks.backend.temporal.create_snapshot.activities.create_snapshot.get_sandbox_class_for_sandbox_id",
        return_value=SandboxClass,
    )
    return sandbox


@pytest.mark.django_db(transaction=True)
def test_create_snapshot_persists_a_backend_tagged_row(activity_environment, mocker, github_integration) -> None:
    external_id = f"sn-{uuid.uuid4().hex[:8]}"
    sandbox = _mock_sandbox(mocker, external_id)

    snapshot_id = async_to_sync(activity_environment.run)(
        create_snapshot,
        CreateSnapshotInput(context=_context(github_integration.id), sandbox_id="box-abc123def456"),
    )

    snapshot = SandboxSnapshot.objects.get(id=snapshot_id)
    assert snapshot.external_id == external_id
    assert snapshot.status == SandboxSnapshot.Status.COMPLETE
    assert snapshot.repos == ["PostHog/posthog"]
    assert snapshot.sandbox_backend == "hogland"
    assert snapshot.metadata["snapshot_kind"] == SNAPSHOT_KIND_FILESYSTEM
    # The clone credentials are scrubbed before the snapshot captures the disk.
    scrub_command = sandbox.execute.call_args.args[0]
    assert "git remote set-url origin https://github.com/posthog/posthog.git" in scrub_command


@pytest.mark.django_db(transaction=True)
def test_create_snapshot_supersedes_older_rows_for_the_same_repo_and_backend(
    activity_environment, mocker, github_integration
) -> None:
    superseded = SandboxSnapshot.objects.create(
        integration_id=github_integration.id,
        repos=["posthog/posthog"],
        status=SandboxSnapshot.Status.COMPLETE,
        external_id=f"sn-{uuid.uuid4().hex[:8]}",
        metadata={"sandbox_backend": "hogland"},
    )
    other_backend = SandboxSnapshot.objects.create(
        integration_id=github_integration.id,
        repos=["PostHog/posthog"],
        status=SandboxSnapshot.Status.COMPLETE,
        external_id=f"snapshot-{uuid.uuid4()}",
    )
    other_repo = SandboxSnapshot.objects.create(
        integration_id=github_integration.id,
        repos=["PostHog/other"],
        status=SandboxSnapshot.Status.COMPLETE,
        external_id=f"sn-{uuid.uuid4().hex[:8]}",
        metadata={"sandbox_backend": "hogland"},
    )
    _mock_sandbox(mocker, f"sn-{uuid.uuid4().hex[:8]}")

    snapshot_id = async_to_sync(activity_environment.run)(
        create_snapshot,
        CreateSnapshotInput(context=_context(github_integration.id), sandbox_id="box-abc123def456"),
    )

    remaining = set(SandboxSnapshot.objects.values_list("id", flat=True))
    assert superseded.id not in remaining
    assert {uuid.UUID(snapshot_id), other_backend.id, other_repo.id} <= remaining


@pytest.mark.django_db(transaction=True)
def test_create_snapshot_refuses_to_snapshot_when_the_scrub_fails(
    activity_environment, mocker, github_integration
) -> None:
    sandbox = _mock_sandbox(mocker, "sn-unused")
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="boom", exit_code=1, error=None)

    with pytest.raises(RuntimeError, match="scrub"):
        async_to_sync(activity_environment.run)(
            create_snapshot,
            CreateSnapshotInput(context=_context(github_integration.id), sandbox_id="box-abc123def456"),
        )

    sandbox.create_snapshot.assert_not_called()
    assert SandboxSnapshot.objects.count() == 0
