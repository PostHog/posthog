import time

import pytest

from asgiref.sync import async_to_sync

from posthog.models.integration import Integration

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.process_task.activities.check_snapshot_exists_for_repository import (
    CheckSnapshotExistsForRepositoryInput,
    CheckSnapshotExistsForRepositoryOutput,
    check_snapshot_exists_for_repository,
)


class TestCheckSnapshotExistsForRepositoryActivity:
    def _create_snapshot(
        self, github_integration, repos, status=SandboxSnapshot.Status.COMPLETE, external_id="test-snap-123"
    ):
        return SandboxSnapshot.objects.create(
            integration=github_integration,
            repos=repos,
            status=status,
            external_id=external_id,
        )

    def _cleanup_snapshot(self, snapshot):
        snapshot.delete()

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_found(self, activity_environment, github_integration):
        snapshot = self._create_snapshot(github_integration, repos=["test-owner/test-repo", "other-owner/other-repo"])

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(snapshot.id)
        finally:
            self._cleanup_snapshot(snapshot)

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_not_found(self, activity_environment, github_integration):
        input_data = CheckSnapshotExistsForRepositoryInput(
            github_integration_id=github_integration.id, repository="nonexistent/repo"
        )
        result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

        assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
        assert result.exists is False
        assert result.snapshot_id is None

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_repo_not_in_snapshot(self, activity_environment, github_integration):
        snapshot = self._create_snapshot(
            github_integration, repos=["other-owner/other-repo", "another-owner/another-repo"]
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            self._cleanup_snapshot(snapshot)

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_ignores_incomplete_snapshots(
        self, activity_environment, github_integration
    ):
        in_progress_snapshot = self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.IN_PROGRESS,
            external_id="in-progress-snap",
        )
        error_snapshot = self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.ERROR,
            external_id="error-snap",
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            self._cleanup_snapshot(in_progress_snapshot)
            self._cleanup_snapshot(error_snapshot)

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_returns_latest_complete(
        self, activity_environment, github_integration
    ):
        older_snapshot = self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id="older-snap",
        )

        time.sleep(0.01)

        newer_snapshot = self._create_snapshot(
            github_integration,
            repos=["test-owner/test-repo", "other-owner/other-repo"],
            status=SandboxSnapshot.Status.COMPLETE,
            external_id="newer-snap",
        )

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(newer_snapshot.id)
        finally:
            self._cleanup_snapshot(older_snapshot)
            self._cleanup_snapshot(newer_snapshot)

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_case_insensitive(self, activity_environment, github_integration):
        snapshot = self._create_snapshot(github_integration, repos=["TestOwner/TestRepo"])

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="testowner/testrepo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is True
            assert result.snapshot_id == str(snapshot.id)
        finally:
            self._cleanup_snapshot(snapshot)

    @pytest.mark.django_db
    def test_check_snapshot_exists_for_repository_different_integration(
        self, activity_environment, github_integration, team
    ):
        other_integration = Integration.objects.create(
            team=team,
            kind="github",
            config={"access_token": "other_fake_token"},
        )

        snapshot = self._create_snapshot(other_integration, repos=["test-owner/test-repo"])

        try:
            input_data = CheckSnapshotExistsForRepositoryInput(
                github_integration_id=github_integration.id, repository="test-owner/test-repo"
            )
            result = async_to_sync(activity_environment.run)(check_snapshot_exists_for_repository, input_data)

            assert isinstance(result, CheckSnapshotExistsForRepositoryOutput)
            assert result.exists is False
            assert result.snapshot_id is None
        finally:
            self._cleanup_snapshot(snapshot)
            other_integration.delete()
