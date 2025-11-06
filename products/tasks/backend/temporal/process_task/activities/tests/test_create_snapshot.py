import os
import uuid

import pytest

from asgiref.sync import sync_to_async

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.create_snapshot import CreateSnapshotInput, create_snapshot


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestCreateSnapshotActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_snapshot_real(self, activity_environment, github_integration, ateam):
        """Test real snapshot creation with actual sandbox."""
        config = SandboxEnvironmentConfig(
            name="test-create-snapshot",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        created_snapshot = None
        created_snapshot_external_id = None
        try:
            # Create a real sandbox
            sandbox = await SandboxEnvironment.create(config)

            input_data = CreateSnapshotInput(
                sandbox_id=sandbox.id,
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                repository="test-owner/test-repo",
                task_id="test-task-123",
                distinct_id="test-user-id",
            )

            # This will create a real snapshot and wait for it to complete
            result = await activity_environment.run(create_snapshot, input_data)

            # Verify a UUID was returned
            assert result is not None
            uuid.UUID(result)  # Should not raise

            # Verify snapshot was created in the database
            created_snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=result)
            created_snapshot_external_id = created_snapshot.external_id
            assert created_snapshot.external_id is not None
            assert created_snapshot.integration_id == github_integration.id
            assert "test-owner/test-repo" in created_snapshot.repos
            assert created_snapshot.status == SandboxSnapshot.Status.COMPLETE

            # Verify the snapshot exists in provider
            snapshot_status = await SandboxEnvironment.get_snapshot_status(created_snapshot.external_id)
            assert snapshot_status.value == "complete"

        finally:
            if sandbox:
                await sandbox.destroy()

            if created_snapshot:
                await sync_to_async(created_snapshot.delete)()

            if created_snapshot_external_id:
                await SandboxEnvironment.delete_snapshot(created_snapshot_external_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_snapshot_with_existing_base_snapshot(self, activity_environment, github_integration, ateam):
        """Test snapshot creation with existing base snapshot repos."""
        # Create a base snapshot in the database (using a fake external ID since we're not creating it in Runloop)
        base_snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            external_id=f"fake_base_{uuid.uuid4().hex[:8]}",
            repos=["existing-owner/existing-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        config = SandboxEnvironmentConfig(
            name="test-create-snapshot-with-base",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        created_snapshot = None
        created_snapshot_external_id = None
        try:
            sandbox = await SandboxEnvironment.create(config)

            input_data = CreateSnapshotInput(
                sandbox_id=sandbox.id,
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                repository="new-owner/new-repo",
                task_id="test-task-with-base",
                distinct_id="test-user-id",
            )

            result = await activity_environment.run(create_snapshot, input_data)

            # Verify new snapshot includes both repos
            created_snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=result)
            created_snapshot_external_id = created_snapshot.external_id
            assert created_snapshot.external_id is not None
            assert "existing-owner/existing-repo" in created_snapshot.repos
            assert "new-owner/new-repo" in created_snapshot.repos
            assert len(created_snapshot.repos) == 2

            # Verify the snapshot actually exists in Runloop
            snapshot_status = await SandboxEnvironment.get_snapshot_status(created_snapshot.external_id)
            assert snapshot_status.value == "complete"

        finally:
            await sync_to_async(base_snapshot.delete)()
            if sandbox:
                await sandbox.destroy()
            if created_snapshot:
                await sync_to_async(created_snapshot.delete)()
            if created_snapshot_external_id:
                await SandboxEnvironment.delete_snapshot(created_snapshot_external_id)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_create_snapshot_sandbox_not_found(self, activity_environment, github_integration, ateam):
        input_data = CreateSnapshotInput(
            sandbox_id="non-existent-sandbox-id",
            github_integration_id=github_integration.id,
            team_id=ateam.id,
            repository="test-owner/test-repo",
            task_id="test-task-not-found",
            distinct_id="test-user-id",
        )

        with pytest.raises(SandboxNotFoundError):
            await activity_environment.run(create_snapshot, input_data)
