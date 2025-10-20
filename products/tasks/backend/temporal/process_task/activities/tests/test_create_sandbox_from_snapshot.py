import os
import uuid

import pytest

from asgiref.sync import sync_to_async

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import SandboxProvisionError, SnapshotNotFoundError
from products.tasks.backend.temporal.process_task.activities.create_sandbox_from_snapshot import (
    CreateSandboxFromSnapshotInput,
    create_sandbox_from_snapshot,
)

from .constants import BASE_SNAPSHOT


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestCreateSandboxFromSnapshotActivity:
    async def _create_snapshot(self, github_integration, external_id=None, status=SandboxSnapshot.Status.COMPLETE):
        if external_id is None:
            external_id = str(uuid.uuid4())
        return await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=external_id,
            status=status,
        )

    async def _cleanup_snapshot(self, snapshot):
        await sync_to_async(snapshot.delete)()

    async def _cleanup_sandbox(self, sandbox_id):
        sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
        await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_sandbox_from_snapshot_success(self, activity_environment, github_integration):
        snapshot = await self._create_snapshot(github_integration, external_id=BASE_SNAPSHOT["external_id"])
        task_id = "test-task-123"
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id), task_id=task_id, distinct_id="test-user-id"
            )
            sandbox_id = await activity_environment.run(create_sandbox_from_snapshot, input_data)

            assert isinstance(sandbox_id, str)
            assert len(sandbox_id) > 0

            sandbox = await SandboxEnvironment.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id
            assert sandbox.status in ["pending", "initializing", "running"]

        finally:
            await self._cleanup_snapshot(snapshot)
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_sandbox_from_snapshot_not_found(self, activity_environment):
        input_data = CreateSandboxFromSnapshotInput(
            snapshot_id=str(uuid.uuid4()),
            task_id="test-task-456",
            distinct_id="test-user-id",
        )

        with pytest.raises(SnapshotNotFoundError):
            await activity_environment.run(create_sandbox_from_snapshot, input_data)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_sandbox_from_snapshot_with_invalid_external_id(
        self, activity_environment, github_integration
    ):
        snapshot = await self._create_snapshot(github_integration, external_id="invalid-snapshot-id")
        task_id = "test-task-789"
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id), task_id=task_id, distinct_id="test-user-id"
            )

            with pytest.raises(SandboxProvisionError):
                sandbox_id = await activity_environment.run(create_sandbox_from_snapshot, input_data)

        finally:
            await self._cleanup_snapshot(snapshot)
            if sandbox_id:
                await self._cleanup_sandbox(sandbox_id)
