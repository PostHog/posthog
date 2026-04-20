"""Tests for visual_review Celery tasks."""

import pytest
from unittest.mock import patch

from products.visual_review.backend import logic
from products.visual_review.backend.diffing import process_diffs
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.tasks.tasks import process_run_diffs
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestProcessRunDiffs:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_process_run_diffs_completes_run(self, repo):
        # Create run without any changed snapshots
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="hash1")],
            ),
            team_id=repo.team_id,
        )

        # Process (should complete immediately since no changed snapshots need diffing)
        process_run_diffs(str(create_result.run_id))

        # Check run is completed
        run = api.get_run(create_result.run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.completed_at is not None

    def test_process_run_diffs_handles_error(self, repo):
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

        with patch("products.visual_review.backend.diffing.process_diffs") as mock:
            mock.side_effect = Exception("Something went wrong")

            with pytest.raises(Exception):
                process_run_diffs(str(create_result.run_id))

        # Check run is marked as failed
        run = api.get_run(create_result.run_id)
        assert run.status == RunStatus.FAILED
        assert "Something went wrong" in (run.error_message or "")

    def testprocess_diffs_skips_unchanged(self, repo):
        # Create artifact that exists for both baseline and current
        logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="same_hash",
            storage_path="visual_review/same_hash",
        )

        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="same_hash")],
                baseline_hashes={"Button": "same_hash"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        with patch(
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"Button": "same_hash"},
        ):
            logic.complete_run(create_result.run_id)

        # Process - should skip unchanged snapshot
        process_diffs(create_result.run_id)

        # Snapshot should remain unchanged
        snapshots = api.get_run_snapshots(create_result.run_id)
        assert len(snapshots) == 1
        assert snapshots[0].result == SnapshotResult.UNCHANGED

    def testprocess_diffs_skips_new(self, repo):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="NewComponent", content_hash="new_hash")],
                baseline_hashes={},  # No baseline
            ),
            team_id=repo.team_id,
        )

        # Process - should skip new snapshot (no baseline to diff against)
        process_diffs(create_result.run_id)

        snapshots = api.get_run_snapshots(create_result.run_id)
        assert len(snapshots) == 1
        assert snapshots[0].result == SnapshotResult.NEW

    def testprocess_diffs_attempts_diff_for_changed(self, repo):
        # Create baseline artifact
        logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="old_hash",
            storage_path="visual_review/old_hash",
        )
        # Create current artifact
        logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )

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
                "products.visual_review.backend.logic._resolve_baselines",
                return_value={"Button": "old_hash"},
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            logic.complete_run(create_result.run_id)

        # Process - should attempt to diff but fail because artifacts aren't in storage
        with patch("products.visual_review.backend.diffing.logger") as mock_logger:
            process_diffs(create_result.run_id)

            # Check that warning was logged about missing artifacts
            mock_logger.warning.assert_called()
            call_args = [call[0][0] for call in mock_logger.warning.call_args_list]
            assert any("diff_skipped_missing_artifact" in arg for arg in call_args)
