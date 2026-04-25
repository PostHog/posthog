import uuid

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.create_snapshot.activities.create_snapshot import (
    CreateSnapshotInput,
    create_snapshot,
)
from products.tasks.backend.temporal.create_snapshot.activities.get_snapshot_context import SnapshotContext
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError

SANDBOX_CLASS = "products.tasks.backend.temporal.create_snapshot.activities.create_snapshot.Sandbox"


class TestCreateSnapshotActivity:
    def _create_context(self, github_integration, repository) -> SnapshotContext:
        return SnapshotContext(
            github_integration_id=github_integration.id,
            repository=repository,
            team_id=github_integration.team_id,
        )

    @pytest.mark.django_db
    def test_create_snapshot_success(self, activity_environment, github_integration):
        mock_sandbox = MagicMock()
        mock_sandbox.id = "sb-test123"
        mock_sandbox.create_snapshot.return_value = "im-test456"

        with patch(f"{SANDBOX_CLASS}.get_by_id", return_value=mock_sandbox) as mock_get:
            context = self._create_context(github_integration, "test-owner/test-repo")
            input_data = CreateSnapshotInput(context=context, sandbox_id="sb-test123")

            result = async_to_sync(activity_environment.run)(create_snapshot, input_data)

            mock_get.assert_called_once_with("sb-test123")
            mock_sandbox.create_snapshot.assert_called_once()

            assert result is not None
            uuid.UUID(result)

            created_snapshot = SandboxSnapshot.objects.get(id=result)
            assert created_snapshot.external_id == "im-test456"
            assert created_snapshot.integration_id == github_integration.id
            assert created_snapshot.repos == ["test-owner/test-repo"]
            assert created_snapshot.status == SandboxSnapshot.Status.COMPLETE

    @pytest.mark.django_db
    def test_create_snapshot_contains_only_current_repo(self, activity_environment, github_integration):
        """Verify that snapshots only contain the current repository, not accumulated repos from base."""
        base_snapshot = SandboxSnapshot.objects.create(
            integration=github_integration,
            external_id=f"fake_base_{uuid.uuid4().hex[:8]}",
            repos=["existing-owner/existing-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
        )

        mock_sandbox = MagicMock()
        mock_sandbox.id = "sb-test789"
        mock_sandbox.create_snapshot.return_value = "im-test012"

        try:
            with patch(f"{SANDBOX_CLASS}.get_by_id", return_value=mock_sandbox) as mock_get:
                context = self._create_context(github_integration, "new-owner/new-repo")
                input_data = CreateSnapshotInput(context=context, sandbox_id="sb-test789")

                result = async_to_sync(activity_environment.run)(create_snapshot, input_data)

                mock_get.assert_called_once_with("sb-test789")
                mock_sandbox.create_snapshot.assert_called_once()

                created_snapshot = SandboxSnapshot.objects.get(id=result)
                assert created_snapshot.repos == ["new-owner/new-repo"]
                assert len(created_snapshot.repos) == 1
                assert "existing-owner/existing-repo" not in created_snapshot.repos
        finally:
            base_snapshot.delete()

    @pytest.mark.django_db
    def test_create_snapshot_sandbox_not_found(self, activity_environment, github_integration):
        with patch(
            f"{SANDBOX_CLASS}.get_by_id",
            side_effect=SandboxNotFoundError(
                "Sandbox non-existent-sandbox-id not found",
                {"sandbox_id": "non-existent-sandbox-id"},
                cause=Exception("not found"),
            ),
        ):
            context = self._create_context(github_integration, "test-owner/test-repo")
            input_data = CreateSnapshotInput(context=context, sandbox_id="non-existent-sandbox-id")

            with pytest.raises(SandboxNotFoundError):
                async_to_sync(activity_environment.run)(create_snapshot, input_data)
