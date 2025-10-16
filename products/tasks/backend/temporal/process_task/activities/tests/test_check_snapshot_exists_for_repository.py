import time

import pytest

from asgiref.sync import sync_to_async

from posthog.models.integration import Integration

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.process_task.activities.check_snapshot_exists_for_repository import (
    CheckSnapshotExistsForRepositoryInput,
    CheckSnapshotExistsForRepositoryOutput,
    check_snapshot_exists_for_repository,
)


class TestCheckSnapshotExistsForRepositoryActivity:
    async def _create_snapshot(
        self, github_integration, repos, status=SandboxSnapshot.Status.COMPLETE, external_id="test-snap-123"
    ):
        return await sync_to_async(SandboxSnapshot.objects.create)(
            integration=github_integration,
            repos=repos,
            status=status,
            external_id=external_id,
        )

    async def _cleanup_snapshot(self, snapshot):
        await sync_to_async(snapshot.delete)()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_found(self, activity_environment, github_integration):
        snapshot = await self._create_snapshot(
            github_integration, repos=["test-owner/test-repo", "other-owner/other-repo"]
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(snapshot.id)
        finally:
            await self._cleanup_snapshot(snapshot)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_not_found(self, activity_environment, github_integration):
        input_data = CheckSnapshotExistsForRepositoryInput(
            github_integration_id=github_integration.id, repository="nonexistent/repo"
        )
        result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

        assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
        assert result.exists is False
        assert result.snapshot_id is None

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_repo_not_in_snapshot(
        self, activity_environment, github_integration
    ):
        snapshot = await self._create_snapshot(
            github_integration, repos=["other-owner/other-repo", "another-owner/another-repo"]
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            await self._cleanup_snapshot(snapshot)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_ignores_incomplete_snapshots(
        self, activity_environment, github_integration
    ):
        # Create snapshots with different statuses
        in_progress_snapshot = await self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id="in-progress-snap",
        )
        error_snapshot = await self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.ERROR,
            external_id="error-snap",
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            # Should not find incomplete snapshots
            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            await self._cleanup_snapshot(in_progress_snapshot)
            await self._cleanup_snapshot(error_snapshot)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_returns_latest_complete(
        self, activity_environment, github_integration
    ):
        # Create multiple snapshots, with the latest being complete
        older_snapshot = await self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id="older-snap",
        )

        # Add delay to ensure different created_at times
        time.sleep(0.01)

        newer_snapshot = await self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo", "other-owner/other-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id="newer-snap",
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            # Should return the newer snapshot
            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(newer_snapshot.id)
        finally:
            await self._cleanup_snapshot(older_snapshot)
            await self._cleanup_snapshot(newer_snapshot)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_case_insensitive(
        self, activity_environment, github_integration
    ):
        # Create snapshot with mixed case repository name
        snapshot = await self._create_snapshot(github_integration, repos=["TestOwner/TestRepo"])

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="testowner/testrepo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(snapshot.id)
        finally:
            await self._cleanup_snapshot(snapshot)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_check_snapshot_exists_for_repository_different_integration(
        self, activity_environment, github_integration, ateam
    ):
        other_integration = await sync_to_async(Integration.objects.create)(
            team=ateam,
            kind="github",
            config={"access_token": "other_fake_token"},
        )

        snapshot = await self._create_snapshot(other_integration, repos=["test-owner/test-repo"])

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = await activity_environment.run(check_snapshot_exists_for_repository, input_data)

            # Should not find snapshot from different integration
            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            await self._cleanup_snapshot(snapshot)
            await sync_to_async(other_integration.delete)()
