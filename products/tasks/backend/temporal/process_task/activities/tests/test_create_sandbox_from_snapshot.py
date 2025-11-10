import os
import uuid

import pytest

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import SandboxProvisionError, SnapshotNotFoundError
from products.tasks.backend.temporal.process_task.activities.create_sandbox_from_snapshot import (
    CreateSandboxFromSnapshotInput,
    create_sandbox_from_snapshot,
)

from .constants import BASE_SNAPSHOT


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCreateSandboxFromSnapshotActivity:
    def _create_snapshot(self, github_integration, external_id=None, status=SandboxSnapshot.Status.COMPLETE):
        if external_id is None:
            external_id = str(uuid.uuid4())
        return SandboxSnapshot.objects.create(
            integration=github_integration,
            external_id=external_id,
            status=status,
        )

    def _cleanup_snapshot(self, snapshot):
        snapshot.delete()

    def _cleanup_sandbox(self, sandbox_id):
        sandbox = Sandbox.get_by_id(sandbox_id)
        sandbox.destroy()

    @pytest.mark.django_db
    def test_create_sandbox_from_snapshot_success(self, activity_environment, github_integration):
        snapshot = self._create_snapshot(github_integration, external_id=BASE_SNAPSHOT["external_id"])
        task_id = "test-task-123"
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id), task_id=task_id, distinct_id="test-user-id"
            )
            sandbox_id = activity_environment.run(create_sandbox_from_snapshot, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id
            assert sandbox.status in ["pending", "initializing", "running"]

        finally:
            self._cleanup_snapshot(snapshot)
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)

    @pytest.mark.django_db
    def test_create_sandbox_from_snapshot_not_found(self, activity_environment):
        input_data = CreateSandboxFromSnapshotInput(
            snapshot_id=str(uuid.uuid4()),
            task_id="test-task-456",
            distinct_id="test-user-id",
        )

        with pytest.raises(SnapshotNotFoundError):
            activity_environment.run(create_sandbox_from_snapshot, input_data)

    @pytest.mark.django_db
    def test_create_sandbox_from_snapshot_with_invalid_external_id(self, activity_environment, github_integration):
        snapshot = self._create_snapshot(github_integration, external_id="invalid-snapshot-id")
        task_id = "test-task-789"
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id), task_id=task_id, distinct_id="test-user-id"
            )

            with pytest.raises(SandboxProvisionError):
                sandbox_id = activity_environment.run(create_sandbox_from_snapshot, input_data)

        finally:
            self._cleanup_snapshot(snapshot)
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)
