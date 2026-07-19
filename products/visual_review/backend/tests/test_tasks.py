"""Tests for visual_review Celery tasks."""

import io
from contextlib import contextmanager

import pytest
from unittest.mock import patch

from PIL import Image

from products.visual_review.backend import diffing, logic
from products.visual_review.backend.diffing import process_diffs
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import (
    ChangeKind,
    ClassificationReason,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.models import RunSnapshot
from products.visual_review.backend.tasks.tasks import post_approval_comment, process_run_diffs
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
        process_run_diffs(repo.team_id, str(create_result.run_id))

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
                process_run_diffs(repo.team_id, str(create_result.run_id))

        # Check run is marked as failed
        run = api.get_run(create_result.run_id)
        assert run.status == RunStatus.FAILED
        assert "Something went wrong" in (run.error_message or "")

    def test_count_processed_diffs_from_persisted_state(self, repo):
        cases: list[tuple[str, dict[str, object], int]] = [
            (
                "persisted_changed",
                {"result": SnapshotResult.CHANGED, "change_kind": ChangeKind.PIXEL},
                1,
            ),
            (
                "below_threshold_unchanged",
                {
                    "result": SnapshotResult.UNCHANGED,
                    "classification_reason": ClassificationReason.BELOW_THRESHOLD,
                },
                1,
            ),
            (
                "exact_unchanged",
                {
                    "result": SnapshotResult.UNCHANGED,
                    "classification_reason": ClassificationReason.EXACT,
                },
                0,
            ),
            ("new", {"result": SnapshotResult.NEW}, 0),
            ("incomplete_changed", {"result": SnapshotResult.CHANGED, "change_kind": ""}, 0),
        ]

        for index, (name, snapshot_fields, expected) in enumerate(cases):
            run, _ = logic.create_run(
                repo_id=repo.id,
                team_id=repo.team_id,
                run_type=RunType.STORYBOOK,
                commit_sha=f"count-{index}",
                branch=f"count-{index}",
                pr_number=None,
                snapshots=[{"identifier": name, "content_hash": f"hash-{index}"}],
            )
            RunSnapshot.objects.filter(run=run).update(**snapshot_fields)

            assert diffing.count_processed_diffs(run.id) == expected, name

    def test_metrics_event_uses_run_id_as_uuid(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="metrics-uuid",
            branch="main",
            pr_number=None,
            snapshots=[],
        )
        capture = mocker.Mock()

        @contextmanager
        def scoped_capture():
            yield capture

        mocker.patch.object(logic, "ph_scoped_capture", scoped_capture)

        logic.capture_run_processing_metrics(run.id, outcome="completed", diffed_count=0)

        assert capture.call_args.kwargs["uuid"] == run.id

    def test_emits_metrics_event_on_success(self, repo):
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

        with (
            patch("products.visual_review.backend.diffing.process_diffs", return_value=0),
            patch("products.visual_review.backend.diffing.count_processed_diffs", return_value=3),
            patch("products.visual_review.backend.logic.capture_run_processing_metrics") as capture,
        ):
            process_run_diffs(repo.team_id, str(create_result.run_id))

        capture.assert_called_once()
        assert capture.call_args.kwargs["outcome"] == "completed"
        assert capture.call_args.kwargs["diffed_count"] == 3

    def test_emits_metrics_event_on_failure(self, repo):
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

        with (
            patch("products.visual_review.backend.diffing.process_diffs", side_effect=Exception("boom")),
            patch("products.visual_review.backend.diffing.count_processed_diffs", side_effect=Exception("count boom")),
            patch("products.visual_review.backend.logic.capture_run_processing_metrics") as capture,
        ):
            with pytest.raises(Exception, match="boom"):
                process_run_diffs(repo.team_id, str(create_result.run_id))

        # Metrics still emitted on the failure path, and the real error is not masked.
        capture.assert_called_once()
        assert capture.call_args.kwargs["outcome"] == "failed"
        assert capture.call_args.kwargs["diffed_count"] == 0

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
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"Button": "same_hash"}, 0),
        ):
            logic.complete_run(create_result.run_id)

        # Process - should skip unchanged snapshot
        process_diffs(create_result.run_id)

        # Snapshot should remain unchanged
        snapshots = api.get_run_snapshots(create_result.run_id).snapshots
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

        snapshots = api.get_run_snapshots(create_result.run_id).snapshots
        assert len(snapshots) == 1
        assert snapshots[0].result == SnapshotResult.NEW

    def testprocess_diffs_skips_new_with_existing_thumbnail(self, repo, mocker):
        thumbnail, _ = logic.get_or_create_artifact(repo.id, "thumb_hash", "visual_review/thumb_hash")
        current, _ = logic.get_or_create_artifact(repo.id, "new_hash", "visual_review/new_hash")
        current.thumbnail = thumbnail
        current.save(update_fields=["thumbnail"])
        create_result = api.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="NewComponent", content_hash="new_hash")],
                baseline_hashes={},
            ),
            team_id=repo.team_id,
        )
        generate_thumbnail = mocker.patch("products.visual_review.backend.diffing._generate_thumbnail_for_new")

        assert process_diffs(create_result.run_id) == 0
        generate_thumbnail.assert_not_called()

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
                "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            logic.complete_run(create_result.run_id)

        # Process - should attempt to diff but fail because artifacts aren't in storage
        with patch("products.visual_review.backend.diffing.logger") as mock_logger:
            diffed_count = process_diffs(create_result.run_id)

            assert diffed_count == 0
            # Check that warning was logged about missing artifacts
            mock_logger.warning.assert_called()
            call_args = [call[0][0] for call in mock_logger.warning.call_args_list]
            assert any("diff_skipped_missing_artifact" in arg for arg in call_args)

    def testprocess_diffs_does_not_repeat_completed_comparisons(self, repo, mocker):
        def png(color: tuple[int, int, int, int]) -> bytes:
            image = Image.new("RGBA", (10, 10), color)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()

        stored_bytes = {
            "old_hash": png((255, 0, 0, 255)),
            "new_hash": png((0, 0, 255, 255)),
        }
        logic.get_or_create_artifact(repo.id, "old_hash", "visual_review/old_hash")
        logic.get_or_create_artifact(repo.id, "new_hash", "visual_review/new_hash")
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
        with (
            patch(
                "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            logic.complete_run(create_result.run_id)

        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            autospec=True,
            side_effect=lambda _storage, content_hash: stored_bytes.get(content_hash),
        )
        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.write",
            autospec=True,
            side_effect=lambda _storage, content_hash, content: (
                stored_bytes.setdefault(content_hash, content) and f"visual_review/{content_hash}"
            ),
        )
        compare_images = mocker.spy(diffing, "compare_images")

        assert process_diffs(create_result.run_id) == 1
        assert process_diffs(create_result.run_id) == 0
        assert compare_images.call_count == 1


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestPostApprovalCommentTask:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/approval")

    def test_calls_logic_helper(self, repo):
        with patch("products.visual_review.backend.logic.post_approval_comment_for_run") as helper:
            post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000001")
        helper.assert_called_once()
        args, kwargs = helper.call_args
        assert str(args[0]) == "00000000-0000-0000-0000-000000000001"
        assert kwargs["team_id"] == repo.team_id

    def test_swallows_unexpected_errors(self, repo):
        with patch(
            "products.visual_review.backend.logic.post_approval_comment_for_run",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise — failure to comment must never block other work.
            post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000002")

    def test_retries_on_rate_limit(self, repo):
        from posthog.egress.github.transport import GitHubRateLimitError

        with (
            patch(
                "products.visual_review.backend.logic.post_approval_comment_for_run",
                side_effect=GitHubRateLimitError("rate limited", retry_after=42),
            ),
            patch.object(post_approval_comment, "retry", side_effect=RuntimeError("retry called")) as retry_mock,
        ):
            with pytest.raises(RuntimeError, match="retry called"):
                post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000003")

        retry_mock.assert_called_once()
        assert retry_mock.call_args.kwargs["countdown"] == 42
