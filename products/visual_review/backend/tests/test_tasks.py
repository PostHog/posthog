"""Tests for visual_review Celery tasks."""

import io
from contextlib import contextmanager
from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from PIL import Image

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority

from products.visual_review.backend import diffing
from products.visual_review.backend.diffing import process_diffs
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import (
    BaselineMode,
    ChangeKind,
    ClassificationReason,
    RunStatus,
    RunType,
    SnapshotResult,
)
from products.visual_review.backend.logic import artifact_store, debt_digest, github_api, ledger_advance, runs
from products.visual_review.backend.logic.baseline_record import METADATA_KEY, BaselineRecord
from products.visual_review.backend.models import Repo, Run, RunSnapshot, ToleratedHash
from products.visual_review.backend.storage import ArtifactStorage
from products.visual_review.backend.tasks import tasks
from products.visual_review.backend.tasks.tasks import (
    post_approval_comment,
    process_run_diffs,
    send_visual_review_debt_digest,
    send_visual_review_debt_digests,
)
from products.visual_review.backend.tests.conftest import (
    PRODUCT_DATABASES,
    VisualReviewTeamScopedTestMixin,
    insert_background_rows,
    make_striped_png,
)
from products.visual_review.backend.tests.logic.ledger_fakes import SEED, approve, seeded_repo


def _make_png(color: tuple[int, int, int, int], size: tuple[int, int] = (10, 10)) -> bytes:
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _make_png_with_single_changed_pixel() -> bytes:
    image = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    image.putpixel((0, 0), (0, 0, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# Every row has its own color, so row alignment has one answer: the page below
# an insert moved down and nothing else changed.
STRIPED_PAGE_ROWS = [(10 + (y * 2) % 240, 40 + y % 100, 200 - y % 150, 255) for y in range(100)]


def _prepare_one_diff(
    repo, mocker, baseline_png: bytes, current_png: bytes, other_pngs: dict[str, bytes] | None = None
):
    stored_bytes = {"old_hash": baseline_png, "new_hash": current_png, **(other_pngs or {})}
    artifact_store.get_or_create_artifact(repo.id, "old_hash", "visual_review/old_hash")
    artifact_store.get_or_create_artifact(repo.id, "new_hash", "visual_review/new_hash")
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
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        ),
        patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
    ):
        runs.complete_run(create_result.run_id)

    mocker.patch(
        "products.visual_review.backend.storage.ArtifactStorage.read",
        autospec=True,
        side_effect=lambda _storage, content_hash: stored_bytes.get(content_hash),
    )
    write = mocker.patch(
        "products.visual_review.backend.storage.ArtifactStorage.write",
        autospec=True,
        side_effect=lambda _storage, content_hash, content: (
            stored_bytes.setdefault(content_hash, content) and f"visual_review/{content_hash}"
        ),
    )
    return create_result.run_id, write


def _process_one_diff(repo, mocker, baseline_png: bytes, current_png: bytes) -> RunSnapshot:
    run_id, _write = _prepare_one_diff(repo, mocker, baseline_png, current_png)
    assert process_diffs(run_id) == 1
    return RunSnapshot.objects.get(run_id=run_id)


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

    def test_metrics_event_uses_run_id_as_uuid(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="metrics-uuid",
                branch="main",
                pr_number=None,
                snapshots=[],
            ),
            team_id=repo.team_id,
        )
        capture = mocker.Mock()

        @contextmanager
        def scoped_capture():
            yield capture

        mocker.patch.object(runs, "ph_scoped_capture", scoped_capture)

        runs.capture_run_processing_metrics(run.id, outcome="completed", diffed_count=0)

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
            patch("products.visual_review.backend.logic.runs.capture_run_processing_metrics") as capture,
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
            patch("products.visual_review.backend.logic.runs.capture_run_processing_metrics") as capture,
        ):
            with pytest.raises(Exception, match="boom"):
                process_run_diffs(repo.team_id, str(create_result.run_id))

        # Metrics still emitted on the failure path, and the real error is not masked.
        capture.assert_called_once()
        assert capture.call_args.kwargs["outcome"] == "failed"
        assert capture.call_args.kwargs["diffed_count"] == 0

    def testprocess_diffs_skips_unchanged(self, repo):
        # Create artifact that exists for both baseline and current
        artifact_store.get_or_create_artifact(
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
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "same_hash"}, 0),
        ):
            runs.complete_run(create_result.run_id)

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
        thumbnail, _ = artifact_store.get_or_create_artifact(repo.id, "thumb_hash", "visual_review/thumb_hash")
        current, _ = artifact_store.get_or_create_artifact(repo.id, "new_hash", "visual_review/new_hash")
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
        artifact_store.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="old_hash",
            storage_path="visual_review/old_hash",
        )
        # Create current artifact
        artifact_store.get_or_create_artifact(
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
                "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            runs.complete_run(create_result.run_id)

        # Process - should attempt to diff but fail because artifacts aren't in storage
        with patch("products.visual_review.backend.diffing.logger") as mock_logger:
            diffed_count = process_diffs(create_result.run_id)

            assert diffed_count == 0
            # Check that warning was logged about missing artifacts
            mock_logger.warning.assert_called()
            call_args = [call[0][0] for call in mock_logger.warning.call_args_list]
            assert any("diff_skipped_missing_artifact" in arg for arg in call_args)

    def testprocess_diffs_does_not_repeat_completed_comparisons(self, repo, mocker):
        stored_bytes = {
            "old_hash": _make_png((255, 0, 0, 255)),
            "new_hash": _make_png((0, 0, 255, 255)),
        }
        artifact_store.get_or_create_artifact(repo.id, "old_hash", "visual_review/old_hash")
        artifact_store.get_or_create_artifact(repo.id, "new_hash", "visual_review/new_hash")
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
                "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
                return_value=({"Button": "old_hash"}, 0),
            ),
            patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay"),
        ):
            runs.complete_run(create_result.run_id)

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

    @pytest.mark.parametrize(
        ("mode", "overlay_storage", "expected_result", "expected_baseline"),
        [
            (BaselineMode.LEDGER, "readable", SnapshotResult.UNCHANGED, "overlay_hash"),
            (BaselineMode.LEDGER, "missing", SnapshotResult.CHANGED, "old_hash"),
            (BaselineMode.LEDGER, "read_fails", SnapshotResult.CHANGED, "old_hash"),
            # A shadow-mode run is decided by the YAML file, so its record never re-points a snapshot.
            (BaselineMode.SHADOW, "readable", SnapshotResult.CHANGED, "old_hash"),
        ],
    )
    def test_process_diffs_tries_the_second_candidate_over_a_threshold(
        self, repo, mocker, mode, overlay_storage, expected_result, expected_baseline
    ):
        run_id, _write = _prepare_one_diff(
            repo,
            mocker,
            baseline_png=_make_png((0, 255, 0, 255), size=(100, 100)),
            current_png=_make_png((255, 0, 0, 255), size=(100, 100)),
            other_pngs={"overlay_hash": _make_png_with_single_changed_pixel()} if overlay_storage == "readable" else {},
        )
        if overlay_storage == "read_fails":
            read_mock = cast(MagicMock, ArtifactStorage.read)
            read_stored = read_mock.side_effect

            def read(storage, content_hash):
                if content_hash == "overlay_hash":
                    raise OSError("object storage unavailable")
                return read_stored(storage, content_hash)

            read_mock.side_effect = read
        artifact_store.get_or_create_artifact(repo.id, "overlay_hash", "visual_review/overlay_hash")
        record = BaselineRecord(
            mode=mode,
            merge_base_sha="s0",
            position=0,
            clamped_to_seed=False,
            containment_complete=True,
            overlay={},
            candidate_approval_ids=(),
            conflicts={},
            second_candidates={"Button": "overlay_hash"},
        )
        Run.objects.filter(id=run_id).update(metadata={METADATA_KEY: record.to_json()})

        assert process_diffs(run_id) == 1

        snapshot = RunSnapshot.objects.get(run_id=run_id)
        assert (snapshot.result, snapshot.baseline_hash) == (expected_result, expected_baseline)
        tolerated = ToleratedHash.objects.filter(repo_id=repo.id, baseline_hash="overlay_hash").exists()
        assert tolerated is (expected_result == SnapshotResult.UNCHANGED)

    def test_process_diffs_counts_below_threshold_comparisons(self, repo, mocker):
        snapshot = _process_one_diff(
            repo,
            mocker,
            baseline_png=_make_png((255, 0, 0, 255), size=(100, 100)),
            current_png=_make_png_with_single_changed_pixel(),
        )

        assert snapshot.result == SnapshotResult.UNCHANGED
        assert snapshot.classification_reason == ClassificationReason.BELOW_THRESHOLD
        assert snapshot.diff_pixel_count is not None
        assert snapshot.diff_pixel_count > 0
        assert snapshot.diff_percentage is not None
        assert snapshot.diff_percentage > 0
        assert ToleratedHash.objects.filter(
            repo_id=repo.id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
        ).exists()

    def test_absorbed_shift_survives_a_failed_diff_upload(self, repo, mocker):
        # The diff pass runs once per run. A noise row that stayed CHANGED
        # because its courtesy diff image did not upload would fail the gate
        # for a change nobody can see.
        run_id, _write = _prepare_one_diff(
            repo,
            mocker,
            baseline_png=make_striped_png(STRIPED_PAGE_ROWS, width=100),
            current_png=insert_background_rows(
                make_striped_png(STRIPED_PAGE_ROWS, width=100), y=20, rows=1, fill=(255, 255, 255, 255)
            ),
        )
        mocker.patch.object(diffing, "_write_diff_artifact", side_effect=RuntimeError("object storage down"))

        assert process_diffs(run_id) == 1

        snapshot = RunSnapshot.objects.get(run_id=run_id)
        assert snapshot.result == SnapshotResult.UNCHANGED
        assert snapshot.classification_reason == ClassificationReason.BELOW_THRESHOLD
        assert snapshot.diff_artifact is None
        assert snapshot.diff_metadata["row_shift"]["inserted_rows"] == 1

    def test_process_diffs_absorbs_a_one_row_shift_but_keeps_its_trace(self, repo, mocker):
        # The whole point of row alignment: a page that moved down by a row is
        # noise, but the run still has to say what moved, and the tolerated
        # hash has to record what the run really cost. Recording the naive
        # percentage here would eat the flakiness headroom of a clean story.
        snapshot = _process_one_diff(
            repo,
            mocker,
            baseline_png=make_striped_png(STRIPED_PAGE_ROWS, width=100),
            current_png=insert_background_rows(
                make_striped_png(STRIPED_PAGE_ROWS, width=100), y=20, rows=1, fill=(255, 255, 255, 255)
            ),
        )

        assert snapshot.result == SnapshotResult.UNCHANGED
        assert snapshot.classification_reason == ClassificationReason.BELOW_THRESHOLD
        assert snapshot.diff_metadata["row_shift"]["inserted_rows"] == 1
        assert snapshot.diff_metadata["row_shift"]["raw_diff_percentage"] > snapshot.diff_percentage
        assert snapshot.diff_artifact is not None

        tolerated = ToleratedHash.objects.get(
            repo_id=repo.id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
        )
        assert tolerated.diff_percentage == snapshot.diff_percentage


class TestCountProcessedDiffs(VisualReviewTeamScopedTestMixin, BaseTest):
    databases = PRODUCT_DATABASES

    @parameterized.expand(
        [
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
    )
    def test_from_persisted_state(self, _name: str, snapshot_fields: dict[str, object], expected: int) -> None:
        repo = api.create_repo(team_id=self.team.id, repo_external_id=99999, repo_full_name="org/test")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha=f"count-{_name}",
                branch=f"count-{_name}",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier=_name, content_hash=f"hash-{_name}")],
            ),
            team_id=repo.team_id,
        )
        RunSnapshot.objects.filter(run=run).update(**snapshot_fields)

        assert diffing.count_processed_diffs(run.id) == expected


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestPostApprovalCommentTask:
    @pytest.fixture
    def repo(self, team):
        return api.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/approval")

    def test_calls_logic_helper(self, repo):
        with patch("products.visual_review.backend.logic.comments.post_approval_comment_for_run") as helper:
            post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000001")
        helper.assert_called_once()
        args, kwargs = helper.call_args
        assert str(args[0]) == "00000000-0000-0000-0000-000000000001"
        assert kwargs["team_id"] == repo.team_id

    def test_swallows_unexpected_errors(self, repo):
        with patch(
            "products.visual_review.backend.logic.comments.post_approval_comment_for_run",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise — failure to comment must never block other work.
            post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000002")

    def test_retries_on_rate_limit(self, repo):
        from posthog.egress.github.transport import GitHubRateLimitError

        with (
            patch(
                "products.visual_review.backend.logic.comments.post_approval_comment_for_run",
                side_effect=GitHubRateLimitError("rate limited", retry_after=42),
            ),
            patch.object(post_approval_comment, "retry", side_effect=RuntimeError("retry called")) as retry_mock,
        ):
            with pytest.raises(RuntimeError, match="retry called"):
                post_approval_comment(repo.team_id, "00000000-0000-0000-0000-000000000003")

        retry_mock.assert_called_once()
        assert retry_mock.call_args.kwargs["countdown"] == 42


class TestDebtDigestTask(VisualReviewTeamScopedTestMixin, BaseTest):
    databases = PRODUCT_DATABASES

    def test_a_held_lock_skips_the_run(self) -> None:
        repo = Repo.objects.create(team_id=self.team.id, repo_external_id=55511, repo_full_name="org/locked")
        cache.set(f"visual_review_debt_digest:{repo.id}", "locked", timeout=60)
        try:
            with patch("products.visual_review.backend.logic.debt_digest.send_debt_digest") as send:
                send_visual_review_debt_digest(self.team.id, str(repo.id))
        finally:
            cache.delete(f"visual_review_debt_digest:{repo.id}")

        # Nothing records what was sent, so an overlapping run would post every reminder twice.
        assert send.call_count == 0

    def test_the_fan_out_gives_each_child_a_deadline_and_skips_a_switched_off_repo(self) -> None:
        repo = Repo.objects.create(
            team_id=self.team.id, repo_external_id=55513, repo_full_name="org/fanned-out", debt_digest_enabled=True
        )
        switched_off = Repo.objects.create(
            team_id=self.team.id, repo_external_id=55514, repo_full_name="org/switched-off"
        )

        with patch("products.visual_review.backend.tasks.tasks.send_visual_review_debt_digest.apply_async") as enqueue:
            send_visual_review_debt_digests()

        # A child without a deadline lets a drained backlog post yesterday's digest next to today's.
        enqueued = {(call.kwargs["args"], call.kwargs["expires"]) for call in enqueue.call_args_list}
        assert ((repo.team_id, str(repo.id)), tasks._DEBT_DIGEST_EXPIRY_SECONDS) in enqueued
        assert str(switched_off.id) not in {args[1] for args, _ in enqueued}

    def test_the_child_posts_the_live_digest(self) -> None:
        repo = Repo.objects.create(team_id=self.team.id, repo_external_id=55512, repo_full_name="org/scheduled")
        try:
            with patch("products.visual_review.backend.logic.debt_digest.send_debt_digest") as send:
                send_visual_review_debt_digest(self.team.id, str(repo.id))
        finally:
            cache.delete(f"visual_review_debt_digest:{repo.id}")

        # Preview mode posts nothing, so a scheduled run in any other mode is a digest nobody gets.
        assert send.call_count == 1
        assert send.call_args.kwargs["mode"] == debt_digest.MODE_LIVE


def _advance_result(commits_unresolved_recently: int = 0) -> ledger_advance.AdvanceResult:
    return ledger_advance.AdvanceResult(
        commits_added=0,
        commits_resolved_late=0,
        approvals_landed=0,
        commits_unresolved_recently=commits_unresolved_recently,
    )


class TestBaselineLedgerTask(VisualReviewTeamScopedTestMixin, BaseTest):
    databases = PRODUCT_DATABASES

    def test_a_run_that_outlived_its_lock_leaves_the_next_holder_lock_alone(self) -> None:
        repo = Repo.objects.create(team_id=self.team.id, repo_external_id=55521, repo_full_name="org/ledger-lock")
        lock_key = f"visual_review_baseline_ledger:{repo.id}:advance"

        def lock_expires_and_another_run_takes_it(_repo, _priority):
            cache.set(lock_key, "next-holder", timeout=60)
            return _advance_result()

        try:
            with patch.object(ledger_advance, "advance", side_effect=lock_expires_and_another_run_takes_it):
                tasks.reconcile_visual_review_baseline_ledger(self.team.id, str(repo.id))
            assert cache.get(lock_key) == "next-holder"
        finally:
            cache.delete(lock_key)

    def _github_at_the_cursor(self, priorities: list[Priority], *, shed_below_critical: bool):
        integration = MagicMock()
        integration.get_default_branch.return_value = "master"
        integration.api_request.return_value = MagicMock(
            status_code=200, json=lambda: {"sha": SEED, "state": "open", "merged": False}
        )

        def factory(_repo, priority=Priority.CRITICAL):
            priorities.append(priority)
            if shed_below_critical and priority != Priority.CRITICAL:
                raise GitHubEgressBudgetExhausted("shed", scope="1")
            return integration

        return patch.object(github_api, "get_github_integration_for_repo", side_effect=factory)

    @parameterized.expand([("advance", False), ("reconcile_approvals", True)])
    def test_the_periodic_reads_ask_for_batch(self, _name: str, reconcile_approvals: bool) -> None:
        repo = seeded_repo(self.team.id, BaselineMode.LEDGER)
        approve(repo, 5, "Button", "b5")
        priorities: list[Priority] = []

        with self._github_at_the_cursor(priorities, shed_below_critical=False):
            tasks.reconcile_visual_review_baseline_ledger(
                self.team.id, str(repo.id), reconcile_approvals=reconcile_approvals
            )

        assert priorities
        assert set(priorities) == {Priority.BATCH}

    @parameterized.expand([("advance", False), ("reconcile_approvals", True)])
    def test_a_read_the_budget_refuses_ends_the_task_quietly_and_frees_the_lock(
        self, _name: str, reconcile_approvals: bool
    ) -> None:
        repo = seeded_repo(self.team.id, BaselineMode.LEDGER)
        approve(repo, 5, "Button", "b5")
        kind = "approvals" if reconcile_approvals else "advance"
        priorities: list[Priority] = []

        with self._github_at_the_cursor(priorities, shed_below_critical=True):
            tasks.reconcile_visual_review_baseline_ledger(
                self.team.id, str(repo.id), reconcile_approvals=reconcile_approvals
            )

        assert priorities
        assert cache.get(f"visual_review_baseline_ledger:{repo.id}:{kind}") is None

    def test_a_push_runs_its_pass_at_normal_while_the_periodic_lock_is_held(self) -> None:
        repo = seeded_repo(self.team.id, BaselineMode.LEDGER)
        approve(repo, 5, "Button", "b5")
        lock_key = f"visual_review_baseline_ledger:{repo.id}:advance"
        cache.set(lock_key, "periodic-holder", timeout=60)
        priorities: list[Priority] = []

        try:
            with self._github_at_the_cursor(priorities, shed_below_critical=False):
                tasks.advance_visual_review_baseline_ledger_after_push(self.team.id, str(repo.id))
        finally:
            cache.delete(lock_key)

        assert priorities
        assert set(priorities) == {Priority.NORMAL}

    def _run_push_task(self, repo, *, retries: int, advance_side_effect) -> MagicMock:
        with (
            patch.object(ledger_advance, "advance", side_effect=advance_side_effect),
            patch.object(
                tasks.advance_visual_review_baseline_ledger_after_push, "retry", side_effect=RuntimeError("retry")
            ) as retry,
        ):
            try:
                tasks.advance_visual_review_baseline_ledger_after_push.apply(
                    args=(self.team.id, str(repo.id)), retries=retries, throw=True
                )
            except RuntimeError:
                pass
        return retry

    @parameterized.expand(
        [
            ("first_run", 0, [_advance_result(commits_unresolved_recently=1)], 5),
            ("third_run", 2, [_advance_result(commits_unresolved_recently=1)], 45),
            ("after_the_last_follow_up", 3, [_advance_result(commits_unresolved_recently=1)], None),
            ("nothing_unresolved", 0, [_advance_result()], None),
            ("refused_read", 0, GitHubEgressBudgetExhausted("shed", scope="1"), None),
        ]
    )
    def test_a_push_follows_up_on_a_recently_unresolved_commit_a_bounded_number_of_times(
        self, _name: str, retries: int, advance_side_effect, expected_countdown: int | None
    ) -> None:
        repo = seeded_repo(self.team.id, BaselineMode.LEDGER)

        retry = self._run_push_task(repo, retries=retries, advance_side_effect=advance_side_effect)

        countdowns = [call.kwargs["countdown"] for call in retry.call_args_list]
        assert countdowns == ([expected_countdown] if expected_countdown is not None else [])

    def test_a_second_push_does_not_follow_up_while_one_follow_up_is_pending(self) -> None:
        repo = seeded_repo(self.team.id, BaselineMode.LEDGER)
        unresolved = [_advance_result(commits_unresolved_recently=1)]

        first = self._run_push_task(repo, retries=0, advance_side_effect=unresolved)
        second = self._run_push_task(repo, retries=0, advance_side_effect=unresolved)

        assert (first.call_count, second.call_count) == (1, 0)
