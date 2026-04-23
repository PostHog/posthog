"""Unit tests for visual_review facade API."""

from uuid import UUID

import pytest
from unittest.mock import patch

from products.visual_review.backend import logic
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import (
    ApproveRunInput,
    ApproveSnapshotInput,
    CreateRunInput,
    SnapshotManifestItem,
    UpdateRepoInput,
)
from products.visual_review.backend.facade.enums import RunType, SnapshotResult
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestProjectAPI:
    def test_create_repo_returns_dto(self, team):
        result = api.create_repo(team_id=team.id, repo_external_id=12345, repo_full_name="org/my-repo")

        assert isinstance(result.id, UUID)
        assert result.team_id == team.id
        assert result.repo_external_id == 12345
        assert result.repo_full_name == "org/my-repo"

    def test_get_repo_returns_dto(self, team):
        created = api.create_repo(team_id=team.id, repo_external_id=11111, repo_full_name="org/test")

        result = api.get_repo(created.id, team_id=team.id)

        assert result.id == created.id
        assert result.repo_full_name == "org/test"

    def test_get_repo_not_found_raises(self, team):
        import uuid

        with pytest.raises(api.RepoNotFoundError):
            api.get_repo(uuid.uuid4(), team_id=team.id)

    def test_list_repos_returns_dtos(self, team):
        api.create_repo(team_id=team.id, repo_external_id=111, repo_full_name="org/first")
        api.create_repo(team_id=team.id, repo_external_id=222, repo_full_name="org/second")

        result = api.list_repos(team.id)

        assert len(result) == 2
        names = {p.repo_full_name for p in result}
        assert names == {"org/first", "org/second"}

    def test_update_repo_sets_baseline_paths(self, team):
        created = api.create_repo(team_id=team.id, repo_external_id=333, repo_full_name="org/test")
        assert created.baseline_file_paths == {}

        result = api.update_repo(
            UpdateRepoInput(
                repo_id=created.id,
                baseline_file_paths={"storybook": ".storybook/snapshots.yml"},
            ),
            team_id=team.id,
        )

        assert result.baseline_file_paths == {"storybook": ".storybook/snapshots.yml"}
        assert result.repo_full_name == "org/test"  # unchanged


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunAPI:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

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
            ),
            team_id=repo.team_id,
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
            ),
            team_id=repo.team_id,
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
            ),
            team_id=repo.team_id,
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
            ),
            team_id=repo.team_id,
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
            ),
            team_id=repo.team_id,
        )

        result = api.complete_run(create_result.run_id)

        assert result.status == "processing"
        mock_delay.assert_called_once_with(str(create_result.run_id))


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveRunAPI:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

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
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        with (
            patch(
                "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            logic.complete_run(create_result.run_id)
        logic.finalize_run(create_result.run_id)

        # Per-snapshot approval is DB only — no run-level finalization
        result = api.approve_run(
            ApproveRunInput(
                run_id=create_result.run_id,
                user_id=user.id,
                snapshots=[ApproveSnapshotInput(identifier="Button", new_hash="new_hash")],
            )
        )

        assert result.approved is False  # Run not finalized
        assert result.approved_at is None

        # Snapshot-level approval fields were set, result preserved
        snapshots = api.get_run_snapshots(create_result.run_id)
        button_snap = next(s for s in snapshots if s.identifier == "Button")
        assert button_snap.result == SnapshotResult.CHANGED
        assert button_snap.approved_hash == "new_hash"
        assert button_snap.review_state == "approved"
