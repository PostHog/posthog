import os
import uuid

import pytest

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.create_snapshot import CreateSnapshotInput, create_snapshot


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCreateSnapshotActivity:
    @pytest.mark.django_db
    def test_create_snapshot_real(self, activity_environment, github_integration, ateam):
        config = SandboxConfig(
            name="test-create-snapshot",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        created_snapshot = None
        created_snapshot_external_id = None
        try:
            sandbox = Sandbox.create(config)

            input_data = CreateSnapshotInput(
                sandbox_id=sandbox.id,
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                repository="test-owner/test-repo",
                task_id="test-task-123",
                distinct_id="test-user-id",
            )

            result = activity_environment.run(create_snapshot, input_data)

            assert result is not None
            uuid.UUID(result)

            created_snapshot = SandboxSnapshot.objects.get(id=result)
            created_snapshot_external_id = created_snapshot.external_id
            assert created_snapshot.external_id is not None
            assert created_snapshot.integration_id == github_integration.id
            assert "test-owner/test-repo" in created_snapshot.repos
            assert created_snapshot.status == SandboxSnapshot.Status.COMPLETE

            snapshot_status = Sandbox.get_snapshot_status(created_snapshot.external_id)
            assert snapshot_status.value == "complete"

        finally:
            if sandbox:
                sandbox.destroy()

            if created_snapshot:
                created_snapshot.delete()

            if created_snapshot_external_id:
                Sandbox.delete_snapshot(created_snapshot_external_id)

    @pytest.mark.django_db
    def test_create_snapshot_with_existing_base_snapshot(self, activity_environment, github_integration, ateam):
        base_snapshot = SandboxSnapshot.objects.create(
            integration=github_integration,
            external_id=f"fake_base_{uuid.uuid4().hex[:8]}",
            repos=["existing-owner/existing-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        config = SandboxConfig(
            name="test-create-snapshot-with-base",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        created_snapshot = None
        created_snapshot_external_id = None
        try:
            sandbox = Sandbox.create(config)

            input_data = CreateSnapshotInput(
                sandbox_id=sandbox.id,
                github_integration_id=github_integration.id,
                team_id=ateam.id,
                repository="new-owner/new-repo",
                task_id="test-task-with-base",
                distinct_id="test-user-id",
            )

            result = activity_environment.run(create_snapshot, input_data)

            created_snapshot = SandboxSnapshot.objects.get(id=result)
            created_snapshot_external_id = created_snapshot.external_id
            assert created_snapshot.external_id is not None
            assert "existing-owner/existing-repo" in created_snapshot.repos
            assert "new-owner/new-repo" in created_snapshot.repos
            assert len(created_snapshot.repos) == 2

            snapshot_status = Sandbox.get_snapshot_status(created_snapshot.external_id)
            assert snapshot_status.value == "complete"

        finally:
            base_snapshot.delete()
            if sandbox:
                sandbox.destroy()
            if created_snapshot:
                created_snapshot.delete()
            if created_snapshot_external_id:
                Sandbox.delete_snapshot(created_snapshot_external_id)

    @pytest.mark.django_db
    def test_create_snapshot_sandbox_not_found(self, activity_environment, github_integration, ateam):
        input_data = CreateSnapshotInput(
            sandbox_id="non-existent-sandbox-id",
            github_integration_id=github_integration.id,
            team_id=ateam.id,
            repository="test-owner/test-repo",
            task_id="test-task-not-found",
            distinct_id="test-user-id",
        )

        with pytest.raises(SandboxNotFoundError):
            activity_environment.run(create_snapshot, input_data)
