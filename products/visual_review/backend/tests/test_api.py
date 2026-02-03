"""Unit tests for visual_review facade API."""

from uuid import UUID

import pytest
from unittest.mock import patch

from products.visual_review.backend import logic
from products.visual_review.backend.api import api
from products.visual_review.backend.api.dtos import (
    ApproveRunInput,
    ApproveSnapshotInput,
    CreateRunInput,
    SnapshotManifestItem,
    UpdateRepoInput,
)
from products.visual_review.backend.domain_types import RunType, SnapshotResult


@pytest.mark.django_db
class TestProjectAPI:
    def test_create_repo_returns_dto(self, team):
        result = api.create_repo(team_id=team.id, name="My Repo")

        assert isinstance(result.id, UUID)
        assert result.team_id == team.id
        assert result.name == "My Repo"

    def test_get_repo_returns_dto(self, team):
        created = api.create_repo(team_id=team.id, name="Test")

        result = api.get_repo(created.id)

        assert result.id == created.id
        assert result.name == "Test"

    def test_get_repo_not_found_raises(self):
        import uuid

        with pytest.raises(api.RepoNotFoundError):
            api.get_repo(uuid.uuid4())

    def test_list_repos_returns_dtos(self, team):
        api.create_repo(team_id=team.id, name="First")
        api.create_repo(team_id=team.id, name="Second")

        result = api.list_repos(team.id)

        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"First", "Second"}

    def test_update_repo_sets_github_config(self, team):
        created = api.create_repo(team_id=team.id, name="Test")
        assert created.repo_full_name == ""
        assert created.baseline_file_paths == {}

        result = api.update_repo(
            UpdateRepoInput(
                repo_id=created.id,
                repo_full_name="posthog/posthog",
                baseline_file_paths={"storybook": ".storybook/snapshots.yml"},
            )
        )

        assert result.repo_full_name == "posthog/posthog"
        assert result.baseline_file_paths == {"storybook": ".storybook/snapshots.yml"}
        assert result.name == "Test"  # unchanged

    def test_update_repo_partial_update(self, team):
        created = api.create_repo(team_id=team.id, name="Original")

        result = api.update_repo(
            UpdateRepoInput(
                repo_id=created.id,
                name="Updated",
            )
        )

        assert result.name == "Updated"
        assert result.repo_full_name == ""  # unchanged


@pytest.mark.django_db
class TestRunAPI:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, name="Test")

    @patch("products.visual_review.backend.storage.ArtifactStorage.get_presigned_upload_url")
    def test_create_run_returns_result_with_uploads(self, mock_presigned, repo):
        mock_presigned.return_value = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "value"},
        }

        result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="hash1", width=100, height=200),
                    SnapshotManifestItem(identifier="Card", content_hash="hash2", width=150, height=250),
                ],
            )
        )

        assert isinstance(result.run_id, UUID)
        assert len(result.uploads) == 2
        upload_hashes = {u.content_hash for u in result.uploads}
        assert upload_hashes == {"hash1", "hash2"}
        # Check upload targets have URL and fields
        for upload in result.uploads:
            assert upload.url == "https://s3.example.com/upload"
            assert upload.fields == {"key": "value"}

    def test_get_run_returns_dto(self, repo):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        result = api.get_run(create_result.run_id)

        assert result.id == create_result.run_id
        assert result.commit_sha == "abc123"
        assert result.summary.total == 0

    def test_get_run_snapshots_returns_dtos(self, repo):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="hash1"),
                    SnapshotManifestItem(identifier="Card", content_hash="hash2"),
                ],
            )
        )

        snapshots = api.get_run_snapshots(create_result.run_id)

        assert len(snapshots) == 2
        assert all(isinstance(s.id, UUID) for s in snapshots)
        identifiers = {s.identifier for s in snapshots}
        assert identifiers == {"Button", "Card"}

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run_no_changes_skips_task(self, mock_delay, repo):
        """Runs with no changes complete immediately without triggering diff task."""
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        result = api.complete_run(create_result.run_id)

        assert result.status == "completed"
        mock_delay.assert_not_called()

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run_with_changes_triggers_task(self, mock_delay, repo):
        """Runs with changes trigger the diff processing task."""
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="new_hash"),
                ],
                baseline_hashes={"Button": "old_hash"},
            )
        )

        result = api.complete_run(create_result.run_id)

        assert result.status == "processing"
        mock_delay.assert_called_once_with(str(create_result.run_id))


@pytest.mark.django_db
class TestApproveRunAPI:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, name="Test")

    def test_approve_run(self, repo, user):
        # Create artifact first (directly via logic since API no longer exposes this)
        logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )

        # Create run with a changed snapshot
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            )
        )

        result = api.approve_run(
            ApproveRunInput(
                run_id=create_result.run_id,
                user_id=user.id,
                snapshots=[ApproveSnapshotInput(identifier="Button", new_hash="new_hash")],
            )
        )

        assert result.approved is True
        assert result.approved_at is not None

        # Check snapshot approval fields were set but result was NOT mutated
        snapshots = api.get_run_snapshots(create_result.run_id)
        button_snap = next(s for s in snapshots if s.identifier == "Button")
        assert button_snap.result == SnapshotResult.CHANGED  # Result preserved
        assert button_snap.approved_hash == "new_hash"  # Approval recorded
