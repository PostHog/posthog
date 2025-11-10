import os
import uuid

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.conftest import get_or_create_test_snapshots
from products.tasks.backend.temporal.exceptions import SandboxProvisionError, SnapshotNotFoundError
from products.tasks.backend.temporal.process_task.activities.create_sandbox_from_snapshot import (
    CreateSandboxFromSnapshotInput,
    create_sandbox_from_snapshot,
)


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
    def test_create_sandbox_from_snapshot_success(self, activity_environment, github_integration, test_task):
        snapshots = get_or_create_test_snapshots(github_integration)
        snapshot = snapshots["single"]
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id),
                task_id=test_task.id,
                distinct_id="test-user-id",
                github_integration_id=github_integration.id,
            )
            output = async_to_sync(activity_environment.run)(create_sandbox_from_snapshot, input_data)

            assert isinstance(output.sandbox_id, str)
            assert len(output.sandbox_id) > 0
            assert isinstance(output.personal_api_key_id, str)

            sandbox_id = output.sandbox_id
            sandbox = Sandbox.get_by_id(sandbox_id)
            assert sandbox.id == sandbox_id

            github_token_check = sandbox.execute("bash -c 'echo $GITHUB_TOKEN'")
            assert github_token_check.exit_code == 0
            assert len(github_token_check.stdout.strip()) > 0, "GITHUB_TOKEN should be set"

            api_key_check = sandbox.execute("bash -c 'echo $POSTHOG_PERSONAL_API_KEY'")
            assert api_key_check.exit_code == 0
            assert len(api_key_check.stdout.strip()) > 0, "POSTHOG_PERSONAL_API_KEY should be set"
            assert api_key_check.stdout.strip().startswith("phx_"), "API key should have correct format"

            api_url_check = sandbox.execute("bash -c 'echo $POSTHOG_API_URL'")
            assert api_url_check.exit_code == 0
            assert len(api_url_check.stdout.strip()) > 0, "POSTHOG_API_URL should be set"

        finally:
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)

    @pytest.mark.django_db
    def test_create_sandbox_from_snapshot_not_found(self, activity_environment, github_integration):
        input_data = CreateSandboxFromSnapshotInput(
            snapshot_id=str(uuid.uuid4()),
            task_id="test-task-456",
            distinct_id="test-user-id",
            github_integration_id=github_integration.id,
        )

        with pytest.raises(SnapshotNotFoundError):
            async_to_sync(activity_environment.run)(create_sandbox_from_snapshot, input_data)

    @pytest.mark.django_db
    def test_create_sandbox_from_snapshot_with_invalid_external_id(
        self, activity_environment, github_integration, test_task
    ):
        snapshot = self._create_snapshot(github_integration, external_id="invalid-snapshot-id")
        sandbox_id = None

        try:
            input_data = CreateSandboxFromSnapshotInput(
                snapshot_id=str(snapshot.id),
                task_id=test_task.id,
                distinct_id="test-user-id",
                github_integration_id=github_integration.id,
            )

            with pytest.raises(SandboxProvisionError):
                output = async_to_sync(activity_environment.run)(create_sandbox_from_snapshot, input_data)
                sandbox_id = output.sandbox_id

        finally:
            self._cleanup_snapshot(snapshot)
            if sandbox_id:
                self._cleanup_sandbox(sandbox_id)
