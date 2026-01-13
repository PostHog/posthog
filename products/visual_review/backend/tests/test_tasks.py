"""Tests for visual_review Celery tasks."""

import pytest
from unittest.mock import patch

from products.visual_review.backend.api import api
from products.visual_review.backend.api.dtos import CreateRunInput, RegisterArtifactInput, SnapshotManifestItem
from products.visual_review.backend.domain_types import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.tasks.tasks import _process_diffs, process_run_diffs


@pytest.mark.django_db
class TestProcessRunDiffs:
    @pytest.fixture
    def project(self, team):
        return api.create_project(team_id=team.id, name="Test")

    def test_process_run_diffs_completes_run(self, project):
        # Create run without any changed snapshots
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="hash1")],
            )
        )

        # Process (should complete immediately since no changed snapshots need diffing)
        process_run_diffs(str(create_result.run_id))

        # Check run is completed
        run = api.get_run(create_result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None

    def test_process_run_diffs_handles_error(self, project):
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        with patch("products.visual_review.backend.tasks.tasks._process_diffs") as mock:
            mock.side_effect = Exception("Something went wrong")

            with pytest.raises(Exception):
                process_run_diffs(str(create_result.run_id))

        # Check run is marked as failed
        run = api.get_run(create_result.run_id)
        assert run.status == RunStatus.FAILED
        assert "Something went wrong" in (run.error_message or "")

    def test_process_diffs_skips_unchanged(self, project):
        # Create artifact that exists for both baseline and current
        api.register_artifact(
            RegisterArtifactInput(
                project_id=project.id,
                content_hash="same_hash",
                storage_path="visual_review/same_hash",
            )
        )

        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="same_hash")],
                baseline_hashes={"Button": "same_hash"},
            )
        )

        # Process - should skip unchanged snapshot
        _process_diffs(create_result.run_id)

        # Snapshot should remain unchanged
        snapshots = api.get_run_snapshots(create_result.run_id)
        assert len(snapshots) == 1
        assert snapshots[0].result == SnapshotResult.UNCHANGED

    def test_process_diffs_skips_new(self, project):
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="NewComponent", content_hash="new_hash")],
                baseline_hashes={},  # No baseline
            )
        )

        # Process - should skip new snapshot (no baseline to diff against)
        _process_diffs(create_result.run_id)

        snapshots = api.get_run_snapshots(create_result.run_id)
        assert len(snapshots) == 1
        assert snapshots[0].result == SnapshotResult.NEW

    def test_process_diffs_logs_changed_snapshots(self, project):
        # Create baseline artifact
        api.register_artifact(
            RegisterArtifactInput(
                project_id=project.id,
                content_hash="old_hash",
                storage_path="visual_review/old_hash",
            )
        )
        # Create current artifact
        api.register_artifact(
            RegisterArtifactInput(
                project_id=project.id,
                content_hash="new_hash",
                storage_path="visual_review/new_hash",
            )
        )

        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            )
        )

        # Process - should attempt to diff changed snapshot
        # Since diff is stubbed, it just logs
        with patch("products.visual_review.backend.tasks.tasks.logger") as mock_logger:
            _process_diffs(create_result.run_id)

            # Check that diff_skipped was logged for the changed snapshot
            mock_logger.info.assert_called()
            call_args = [call[0][0] for call in mock_logger.info.call_args_list]
            assert any("diff_skipped" in arg for arg in call_args)
