"""Unit tests for logic/approvals.py — Approving snapshots and finalizing a run."""

import pytest

from django.db import transaction

from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import ReviewState, RunType, SnapshotResult
from products.visual_review.backend.logic import (
    approvals,
    artifact_store,
    ci_status,
    errors,
    repos,
    run_queries,
    runs,
    toleration,
)
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveRun:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_approve_run(self, repo, user, mocker):
        current_artifact, _ = artifact_store.get_or_create_artifact(
            repo_id=repo.id, content_hash="new_hash", storage_path="p/new"
        )
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        assert updated.approved is True
        assert updated.review_decision == "human_approved"
        assert updated.approved_at is not None
        assert updated.approved_by_id == user.id

        # Result should NOT be mutated - approval is recorded separately
        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.result == SnapshotResult.CHANGED  # Result preserved
        assert snapshot.approved_hash == "new_hash"  # Approval recorded
        assert snapshot.reviewed_at is not None
        assert snapshot.reviewed_by_id == user.id

    def _completed_two_change_run(self, repo, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="ha", storage_path="p/a")
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="hb", storage_path="p/b")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="A", content_hash="ha"),
                    SnapshotManifestItem(identifier="B", content_hash="hb"),
                ],
                baseline_hashes={"A": "olda", "B": "oldb"},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"A": "olda", "B": "oldb"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)
        return run

    def test_finalize_requires_full_resolution(self, repo, user, mocker):
        # Finalize is all-or-nothing: it refuses while any changed/new snapshot is unreviewed.
        run = self._completed_two_change_run(repo, mocker)

        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "A", "new_hash": "ha"}]
        )
        with pytest.raises(errors.RunNotFullyResolvedError, match="B"):
            approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)

        # Resolving the rest lets it finalize.
        approvals.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "B", "new_hash": "hb"}]
        )
        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)
        assert updated.approved is True

    def test_finalize_leaves_tolerated_snapshot_alone(self, repo, user, mocker):
        # A tolerated snapshot resolves the run without being approved or committed.
        run = self._completed_two_change_run(repo, mocker)
        snap_b = run.snapshots.get(identifier="B")
        toleration.mark_snapshot_as_tolerated(run.id, snap_b.id, user.id, repo.team_id)

        updated = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert updated.approved is True
        snapshots = {s.identifier: s for s in updated.snapshots.all()}
        assert snapshots["A"].review_state == ReviewState.APPROVED
        assert snapshots["B"].review_state == ReviewState.TOLERATED  # approve_all did not clobber it

    def test_finalize_is_idempotent_on_approved_run(self, repo, user, mocker):
        # Re-finalizing an already-finalized run is a no-op — no second commit/status/comment.
        run = self._completed_two_change_run(repo, mocker)
        approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
        approved_at = run_queries.get_run_with_snapshots(run.id).approved_at

        again = approvals.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert again.approved is True
        assert again.approved_at == approved_at  # unchanged — the second call did no work

    @pytest.mark.parametrize("add_images", [True, False])
    def test_finalize_always_comments_and_forwards_add_images(self, repo, user, mocker, add_images):
        # The PR comment is always dispatched on finalize; add_images_to_comment_on_pr only
        # controls whether the snapshot images are embedded — forwarded to the task.
        run = self._completed_two_change_run(repo, mocker)
        mocker.patch.object(ci_status, "_post_commit_status")
        mocker.patch.object(transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        delay = mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        approvals.finalize_run(
            run_id=run.id,
            user_id=user.id,
            approve_all=True,
            commit_to_github=True,
            add_images_to_comment_on_pr=add_images,
        )

        assert delay.called is True
        assert delay.call_args.args[2] is add_images


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveSnapshots:
    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=99998, repo_full_name="org/test-snap")

    def test_approve_single_snapshot_db_only(self, repo, user, mocker):
        artifact_store.get_or_create_artifact(repo_id=repo.id, content_hash="new_hash", storage_path="p/new")
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=repo.team_id,
        )
        mocker.patch(
            "products.visual_review.backend.logic.baselines._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        runs.complete_run(run.id)
        runs.finish_processing(run.id)

        updated = approvals.approve_snapshots(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "Button", "new_hash": "new_hash"}],
        )

        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.review_state == "approved"
        assert snapshot.approved_hash == "new_hash"

        # Run-level state should NOT change
        assert updated.approved is False
        assert updated.review_decision == "pending"
