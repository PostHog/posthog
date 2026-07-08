"""Unit tests for visual_review business logic."""

from datetime import timedelta

import pytest

from django.utils import timezone

from products.visual_review.backend import logic
from products.visual_review.backend.facade.enums import ReviewDecision, ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestProjectOperations:
    def test_create_repo(self, team):
        repo = logic.create_repo(team_id=team.id, repo_external_id=12345, repo_full_name="org/my-repo")

        assert repo.team_id == team.id
        assert repo.repo_external_id == 12345
        assert repo.repo_full_name == "org/my-repo"

    def test_get_repo(self, team):
        repo = logic.create_repo(team_id=team.id, repo_external_id=11111, repo_full_name="org/test")

        retrieved = logic.get_repo(repo.id, team_id=team.id)

        assert retrieved.id == repo.id
        assert retrieved.repo_full_name == "org/test"

    def test_get_repo_not_found(self, team):
        import uuid

        with pytest.raises(logic.RepoNotFoundError):
            logic.get_repo(uuid.uuid4(), team_id=team.id)

    def test_list_repos_for_team(self, team):
        logic.create_repo(team_id=team.id, repo_external_id=111, repo_full_name="org/first")
        logic.create_repo(team_id=team.id, repo_external_id=222, repo_full_name="org/second")

        projects = logic.list_repos_for_team(team.id)

        assert len(projects) == 2
        names = {p.repo_full_name for p in projects}
        assert names == {"org/first", "org/second"}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestArtifactOperations:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_get_or_create_artifact_creates_new(self, repo):
        artifact, created = logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
            width=100,
            height=200,
            size_bytes=5000,
        )

        assert created is True
        assert artifact.content_hash == "abc123"
        assert artifact.width == 100
        assert artifact.height == 200
        assert artifact.size_bytes == 5000

    def test_get_or_create_artifact_returns_existing(self, repo):
        artifact1, created1 = logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )
        artifact2, created2 = logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )

        assert created1 is True
        assert created2 is False
        assert artifact1.id == artifact2.id

    def test_get_artifact(self, repo):
        logic.get_or_create_artifact(
            repo_id=repo.id,
            content_hash="xyz789",
            storage_path="visual_review/xyz789",
        )

        artifact = logic.get_artifact(repo.id, "xyz789")

        assert artifact is not None
        assert artifact.content_hash == "xyz789"

    def test_get_artifact_not_found(self, repo):
        artifact = logic.get_artifact(repo.id, "nonexistent")

        assert artifact is None

    def test_find_missing_hashes(self, repo):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="exists1", storage_path="p/exists1")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="exists2", storage_path="p/exists2")

        missing = logic.find_missing_hashes(repo.id, ["exists1", "missing1", "exists2", "missing2"])

        assert set(missing) == {"missing1", "missing2"}

    def test_find_missing_hashes_all_exist(self, repo):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="a", storage_path="p/a")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="b", storage_path="p/b")

        missing = logic.find_missing_hashes(repo.id, ["a", "b"])

        assert missing == []


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunOperations:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_create_run_basic(self, repo):
        run, uploads = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123def456",
            branch="main",
            pr_number=42,
            snapshots=[
                {"identifier": "Button-primary", "content_hash": "hash1"},
                {"identifier": "Button-secondary", "content_hash": "hash2"},
            ],
            baseline_hashes={},
        )

        assert run.repo_id == repo.id
        assert run.run_type == RunType.STORYBOOK
        assert run.commit_sha == "abc123def456"
        assert run.branch == "main"
        assert run.pr_number == 42
        assert run.status == RunStatus.PENDING
        assert run.total_snapshots == 2
        # uploads is a list of dicts with content_hash, url, fields
        upload_hashes = {u["content_hash"] for u in uploads}
        assert upload_hashes == {"hash1", "hash2"}

    def test_create_run_with_existing_artifacts(self, repo):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="existing", storage_path="p/existing")

        run, uploads = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.PLAYWRIGHT,
            commit_sha="abc",
            branch="feat",
            pr_number=None,
            snapshots=[
                {"identifier": "snap1", "content_hash": "existing"},
                {"identifier": "snap2", "content_hash": "new"},
            ],
            baseline_hashes={},
        )

        # Only "new" needs upload, "existing" already has artifact
        assert len(uploads) == 1
        assert uploads[0]["content_hash"] == "new"

    def test_create_run_with_baselines(self, repo, mocker):
        baseline_artifact, _ = logic.get_or_create_artifact(
            repo_id=repo.id, content_hash="baseline_hash", storage_path="p/baseline"
        )

        run, _uploads = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Button", "content_hash": "new_hash"}],
            baseline_hashes={"Button": "baseline_hash"},
        )

        # Classification happens at complete_run time, not create_run time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"Button": "baseline_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        snapshot = run.snapshots.first()
        assert snapshot is not None
        assert snapshot.baseline_artifact_id == baseline_artifact.id
        assert snapshot.result == SnapshotResult.CHANGED

    def test_create_run_snapshot_results(self, repo, mocker):
        baseline_artifact, _ = logic.get_or_create_artifact(
            repo_id=repo.id, content_hash="same_hash", storage_path="p/same"
        )

        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[
                {"identifier": "unchanged", "content_hash": "same_hash"},
                {"identifier": "new", "content_hash": "brand_new"},
                {"identifier": "changed", "content_hash": "different"},
            ],
            baseline_hashes={
                "unchanged": "same_hash",
                "changed": "old_hash",
            },
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"unchanged": "same_hash", "changed": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["unchanged"].result == SnapshotResult.UNCHANGED
        assert snapshots["new"].result == SnapshotResult.NEW
        assert snapshots["changed"].result == SnapshotResult.CHANGED

    def test_create_run_empty(self, repo):
        run, uploads = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
        )

        assert run.total_snapshots == 0
        assert run.changed_count == 0
        assert run.new_count == 0
        assert run.removed_count == 0
        assert run.snapshots.count() == 0
        assert len(uploads) == 0

    def test_add_snapshots_to_run(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
        )
        assert run.total_snapshots == 0

        # Shard 1
        added, _uploads = logic.add_snapshots_to_run(
            run_id=run.id,
            team_id=repo.team_id,
            snapshots=[{"identifier": "btn", "content_hash": "h1"}],
        )
        assert added == 1
        run.refresh_from_db()
        assert run.total_snapshots == 1
        assert run.new_count == 1

        # Shard 2
        added, _uploads = logic.add_snapshots_to_run(
            run_id=run.id,
            team_id=repo.team_id,
            snapshots=[{"identifier": "card", "content_hash": "h2"}],
        )
        assert added == 1
        run.refresh_from_db()
        assert run.total_snapshots == 2
        assert run.new_count == 2
        assert run.snapshots.count() == 2

    def test_add_snapshots_idempotent(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
        )

        for _ in range(2):
            logic.add_snapshots_to_run(
                run_id=run.id,
                team_id=repo.team_id,
                snapshots=[{"identifier": "btn", "content_hash": "h1"}],
            )

        assert run.snapshots.count() == 1

    def test_add_snapshots_rejects_non_pending(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
        )
        logic.finish_processing(run.id)

        with pytest.raises(ValueError, match="pending"):
            logic.add_snapshots_to_run(
                run_id=run.id,
                team_id=repo.team_id,
                snapshots=[{"identifier": "btn", "content_hash": "h1"}],
            )

    def test_complete_run_detects_removals(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "kept", "content_hash": "h1"}],
        )

        # Mock baseline to include an identifier not in the run
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )

        completed = logic.complete_run(run.id)

        assert completed.removed_count == 1
        removed = run.snapshots.get(identifier="deleted")
        assert removed.result == SnapshotResult.REMOVED

    def test_complete_run_partial_skips_removals_off_default_branch(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="feature-x",
            pr_number=7,
            snapshots=[{"identifier": "kept", "content_hash": "h1"}],
            is_partial=True,
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic._run_is_on_default_branch", return_value=False)

        completed = logic.complete_run(run.id)

        assert completed.removed_count == 0
        assert not run.snapshots.filter(identifier="deleted").exists()

    def test_complete_run_partial_ignored_on_default_branch(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="master",
            pr_number=None,
            snapshots=[{"identifier": "kept", "content_hash": "h1"}],
            is_partial=True,
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"kept": "h1", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic._run_is_on_default_branch", return_value=True)

        completed = logic.complete_run(run.id)

        # is_partial must not suppress removal detection on the default branch.
        assert completed.removed_count == 1
        removed = run.snapshots.get(identifier="deleted")
        assert removed.result == SnapshotResult.REMOVED
        # The default-branch correction is persisted, so the run is no longer
        # treated as partial anywhere downstream (status context, UI).
        assert completed.is_partial is False

    def test_complete_run_passes_commit_sha_to_baseline_resolution(self, repo, mocker):
        """complete_run passes run.commit_sha so default-branch baselines are pinned."""
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="deadbeef123",
            branch="master",
            pr_number=None,
            snapshots=[{"identifier": "A", "content_hash": "h1"}],
        )

        mock_resolve = mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"A": "h1"}, 0),
        )

        logic.complete_run(run.id)

        mock_resolve.assert_called_once_with(repo, RunType.STORYBOOK, "master", commit_sha="deadbeef123")

    def test_create_run_with_purpose(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            purpose="observe",
        )
        assert run.purpose == "observe"

    def test_approve_rejects_observe_runs(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "btn", "content_hash": "h1"}],
            purpose="observe",
        )
        logic.finish_processing(run.id)

        with pytest.raises(ValueError, match="Observational"):
            logic.finalize_run(run_id=run.id, user_id=1, approve_all=True)

    def test_get_run(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            baseline_hashes={},
        )

        retrieved = logic.get_run(run.id)

        assert retrieved.id == run.id

    def test_get_run_not_found(self):
        import uuid

        with pytest.raises(logic.RunNotFoundError):
            logic.get_run(uuid.uuid4())

    def test_mark_run_processing(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            baseline_hashes={},
        )

        updated = logic.mark_run_processing(run.id)

        assert updated.status == RunStatus.PROCESSING

    def test_finish_processing_success(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[
                {"identifier": "changed1", "content_hash": "h1"},
                {"identifier": "new1", "content_hash": "h2"},
            ],
            baseline_hashes={"changed1": "old"},
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"changed1": "old"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        # complete_run leaves the run in PROCESSING when there are changes;
        # finish_processing completes it
        updated = logic.finish_processing(run.id)

        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.changed_count == 1
        assert updated.new_count == 1
        assert updated.error_message == ""

    def test_finish_processing_with_error(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            baseline_hashes={},
        )

        updated = logic.finish_processing(run.id, error_message="Something failed")

        assert updated.status == RunStatus.FAILED
        assert updated.error_message == "Something failed"

    def test_update_run_counts_reads_and_writes_through_requested_db(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            baseline_hashes={},
        )

        snapshot_queryset = mocker.Mock()
        snapshot_queryset.values.return_value.annotate.return_value = [
            {"result": SnapshotResult.CHANGED, "n": 2},
            {"result": SnapshotResult.NEW, "n": 1},
        ]
        snapshot_manager = mocker.Mock()
        snapshot_manager.filter.return_value = snapshot_queryset

        run_snapshot_using = mocker.patch.object(logic.RunSnapshot.objects, "using", return_value=snapshot_manager)
        run_save = mocker.patch.object(run, "save")

        logic._update_run_counts(run, using=logic.WRITER_DB)

        run_snapshot_using.assert_called_once_with(logic.WRITER_DB)
        snapshot_manager.filter.assert_called_once_with(run_id=run.id)
        run_save.assert_called_once_with(
            using=logic.WRITER_DB, update_fields=["changed_count", "new_count", "removed_count"]
        )
        assert run.changed_count == 2
        assert run.new_count == 1
        assert run.removed_count == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApproveRun:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_approve_run(self, repo, user, mocker):
        current_artifact, _ = logic.get_or_create_artifact(
            repo_id=repo.id, content_hash="new_hash", storage_path="p/new"
        )
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Button", "content_hash": "new_hash"}],
            baseline_hashes={"Button": "old_hash"},
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        updated = logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

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
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="ha", storage_path="p/a")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="hb", storage_path="p/b")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "A", "content_hash": "ha"}, {"identifier": "B", "content_hash": "hb"}],
            baseline_hashes={"A": "olda", "B": "oldb"},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"A": "olda", "B": "oldb"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)
        return run

    def test_finalize_requires_full_resolution(self, repo, user, mocker):
        # Finalize is all-or-nothing: it refuses while any changed/new snapshot is unreviewed.
        run = self._completed_two_change_run(repo, mocker)

        logic.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "A", "new_hash": "ha"}]
        )
        with pytest.raises(logic.RunNotFullyResolvedError, match="B"):
            logic.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)

        # Resolving the rest lets it finalize.
        logic.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "B", "new_hash": "hb"}]
        )
        updated = logic.finalize_run(run_id=run.id, user_id=user.id, commit_to_github=False)
        assert updated.approved is True

    def test_finalize_leaves_tolerated_snapshot_alone(self, repo, user, mocker):
        # A tolerated snapshot resolves the run without being approved or committed.
        run = self._completed_two_change_run(repo, mocker)
        snap_b = run.snapshots.get(identifier="B")
        logic.mark_snapshot_as_tolerated(run.id, snap_b.id, user.id, repo.team_id)

        updated = logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert updated.approved is True
        snapshots = {s.identifier: s for s in updated.snapshots.all()}
        assert snapshots["A"].review_state == ReviewState.APPROVED
        assert snapshots["B"].review_state == ReviewState.TOLERATED  # approve_all did not clobber it

    def test_finalize_is_idempotent_on_approved_run(self, repo, user, mocker):
        # Re-finalizing an already-finalized run is a no-op — no second commit/status/comment.
        run = self._completed_two_change_run(repo, mocker)
        logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)
        approved_at = logic.get_run_with_snapshots(run.id).approved_at

        again = logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert again.approved is True
        assert again.approved_at == approved_at  # unchanged — the second call did no work

    @pytest.mark.parametrize("add_images", [True, False])
    def test_finalize_always_comments_and_forwards_add_images(self, repo, user, mocker, add_images):
        # The PR comment is always dispatched on finalize; add_images_to_comment_on_pr only
        # controls whether the snapshot images are embedded — forwarded to the task.
        run = self._completed_two_change_run(repo, mocker)
        mocker.patch.object(logic, "_post_commit_status")
        mocker.patch.object(logic.transaction, "on_commit", side_effect=lambda fn, *args, **kwargs: fn())
        delay = mocker.patch("products.visual_review.backend.tasks.tasks.post_approval_comment.delay")

        logic.finalize_run(
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
        return logic.create_repo(team_id=team.id, repo_external_id=99998, repo_full_name="org/test-snap")

    def test_approve_single_snapshot_db_only(self, repo, user, mocker):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="new_hash", storage_path="p/new")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Button", "content_hash": "new_hash"}],
            baseline_hashes={"Button": "old_hash"},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"Button": "old_hash"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        updated = logic.approve_snapshots(
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


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestToleratedHashes:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99997, repo_full_name="org/test-tol")

    def _create_completed_run(
        self, repo, mocker, identifier="Button", current_hash="new_hash", baseline_hash="old_hash"
    ):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash=current_hash, storage_path=f"p/{current_hash}")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": identifier, "content_hash": current_hash}],
            baseline_hashes={identifier: baseline_hash},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({identifier: baseline_hash}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)
        return run

    def test_mark_snapshot_as_tolerated(self, repo, user, mocker):
        run = self._create_completed_run(repo, mocker)
        snapshot = run.snapshots.first()
        assert snapshot.result == SnapshotResult.CHANGED

        updated = logic.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id)

        assert updated.result == SnapshotResult.CHANGED  # result stays technical truth
        assert updated.review_state == "tolerated"
        assert updated.reviewed_by_id == user.id
        assert updated.tolerated_hash_match is not None
        assert updated.tolerated_hash_match.alternate_hash == "new_hash"
        assert updated.tolerated_hash_match.baseline_hash == "old_hash"
        assert updated.tolerated_hash_match.reason == "human"

    def test_mark_unchanged_snapshot_rejected(self, repo, user, mocker):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="same", storage_path="p/same")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Button", "content_hash": "same"}],
            baseline_hashes={"Button": "same"},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"Button": "same"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        snapshot = run.snapshots.first()
        assert snapshot is not None
        with pytest.raises(ValueError, match="Can only mark CHANGED"):
            logic.mark_snapshot_as_tolerated(run.id, snapshot.id, user.id, repo.team_id)

    def test_tolerated_hash_shortcircuits_classification(self, repo, user, mocker):
        from products.visual_review.backend.models import ToleratedHash

        # Create a tolerated hash entry
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
            reason="auto_threshold",
        )

        # Run with the same hashes — should be classified UNCHANGED via cache
        run = self._create_completed_run(repo, mocker)
        snapshot = run.snapshots.first()

        assert snapshot.result == SnapshotResult.UNCHANGED
        assert snapshot.classification_reason == "tolerated_hash"
        assert snapshot.tolerated_hash_match is not None

    def test_tolerated_hash_expires_on_baseline_change(self, repo, user, mocker):
        from products.visual_review.backend.models import ToleratedHash

        # Tolerated hash tied to OLD baseline
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="old_hash",
            alternate_hash="new_hash",
            reason="auto_threshold",
        )

        # Run with a DIFFERENT baseline — tolerated hash should not match
        run = self._create_completed_run(repo, mocker, baseline_hash="updated_baseline")
        snapshot = run.snapshots.first()

        assert snapshot.result == SnapshotResult.CHANGED
        assert snapshot.classification_reason == ""
        assert snapshot.tolerated_hash_match is None

    def test_get_tolerated_hashes_for_identifier(self, repo):
        from products.visual_review.backend.models import ToleratedHash

        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="b1",
            alternate_hash="c1",
            reason="auto_threshold",
        )
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Button",
            baseline_hash="b1",
            alternate_hash="c2",
            reason="human",
        )
        ToleratedHash.objects.create(
            repo=repo,
            team_id=repo.team_id,
            identifier="Other",
            baseline_hash="b1",
            alternate_hash="c3",
            reason="auto_threshold",
        )

        results = logic.get_tolerated_hashes_for_identifier(repo.id, "Button")
        assert len(results) == 2
        assert {r.alternate_hash for r in results} == {"c1", "c2"}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestGetRunSnapshots:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_get_run_snapshots(self, repo):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[
                {"identifier": "A-component", "content_hash": "h1"},
                {"identifier": "B-component", "content_hash": "h2"},
                {"identifier": "C-component", "content_hash": "h3"},
            ],
            baseline_hashes={},
        )

        snapshots = logic.get_run_snapshots(run.id)

        assert len(snapshots) == 3
        # Should be ordered by identifier
        assert [s.identifier for s in snapshots] == ["A-component", "B-component", "C-component"]


@pytest.mark.django_db(transaction=True, databases=PRODUCT_DATABASES)
class TestCommitStatusChecks:
    """Test that GitHub commit status checks are posted at state transitions."""

    @pytest.fixture
    def github_repo(self, team, mock_github_integration):
        return Repo.objects.create(
            team_id=team.id,
            repo_external_id=55555,
            repo_full_name="test-org/test-repo",
            baseline_file_paths={"storybook": ".snapshots.yml"},
        )

    def test_create_run_posts_pending_status(self, github_repo, mock_github_api):
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": "h1"}],
            baseline_hashes={},
        )

        assert len(mock_github_api.status_checks) == 1
        check = mock_github_api.status_checks[0]
        assert check["state"] == "pending"
        assert check["context"] == "PostHog Visual Review / storybook"
        assert f"/visual_review/runs/{run.id}" in check["target_url"]

    def test_complete_run_posts_success_when_no_changes(self, github_repo, mock_github_api, mocker):
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": "same"}],
            baseline_hashes={"snap": "same"},
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"snap": "same"}, 0),
        )
        logic.complete_run(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "No visual changes"
        # A full run posts to the gating context that branch protection evaluates.
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook"

    def test_complete_run_partial_annotates_posted_status(self, github_repo, mock_github_api, mocker):
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="feature-x",
            pr_number=7,
            snapshots=[{"identifier": "snap", "content_hash": "same"}],
            baseline_hashes={"snap": "same"},
            is_partial=True,
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"snap": "same", "deleted": "h2"}, 0),
        )
        mocker.patch("products.visual_review.backend.logic._run_is_on_default_branch", return_value=False)
        logic.complete_run(run.id)

        # A partial run suppresses removal detection, so it must never satisfy
        # the gating status context branch protection evaluates. It posts to a
        # separate "(partial)" context instead, and the description discloses it.
        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "No visual changes (partial run)"
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (partial)"
        # The gating context is never posted green by a partial run.
        gating_context = "PostHog Visual Review / storybook"
        assert all(s["context"] != gating_context for s in statuses)

    def test_complete_run_posts_comment_when_changes_detected(self, github_repo, mock_github_api, mocker):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[
                {"identifier": "changed", "content_hash": "new_h"},
                {"identifier": "added", "content_hash": "brand_new"},
            ],
            baseline_hashes={"changed": "old_h"},
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"changed": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        statuses = mock_github_api.status_checks
        # VR is the gate — unapproved changes post failure
        assert statuses[-1]["state"] == "failure"
        assert "1 changed" in statuses[-1]["description"]
        assert "1 new" in statuses[-1]["description"]
        assert len(mock_github_api.issue_comments) == 1
        assert mock_github_api.issue_comments[0]["action"] == "created"
        comment = mock_github_api.issue_comments[0]["body"]
        assert "Review and approve in PostHog Visual Review" in comment
        assert f"/visual_review/runs/{run.id}" in comment
        # Verify comment ID stored for future updates
        run.refresh_from_db()
        assert run.metadata["github_comment_id"] is not None

    def test_subsequent_run_updates_existing_comment(self, github_repo, mock_github_api):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run1, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc111",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "changed", "content_hash": "new_h"}],
            baseline_hashes={"changed": "old_h"},
        )
        logic.finish_processing(run1.id)

        run2, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc222",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "changed", "content_hash": "newer_h"}],
            baseline_hashes={"changed": "old_h"},
        )
        logic.finish_processing(run2.id)

        created = [c for c in mock_github_api.issue_comments if c["action"] == "created"]
        updated = [c for c in mock_github_api.issue_comments if c["action"] == "updated"]
        assert len(created) == 1
        assert len(updated) == 1
        assert f"/visual_review/runs/{run2.id}" in updated[0]["body"]

    def test_complete_run_does_not_comment_twice_on_retry(self, github_repo, mock_github_api):
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "changed", "content_hash": "new_h"}],
            baseline_hashes={"changed": "old_h"},
        )

        logic.finish_processing(run.id)
        logic.finish_processing(run.id)

        assert len(mock_github_api.issue_comments) == 1

    @pytest.mark.parametrize(
        "enable_pr_comments, pr_number, snapshots, baseline_hashes, purpose",
        [
            (False, 1, [{"identifier": "changed", "content_hash": "new_h"}], {"changed": "old_h"}, "review"),
            (True, None, [{"identifier": "changed", "content_hash": "new_h"}], {"changed": "old_h"}, "review"),
            (True, 1, [{"identifier": "snap", "content_hash": "same"}], {"snap": "same"}, "review"),
            (True, 1, [{"identifier": "changed", "content_hash": "new_h"}], {"changed": "old_h"}, "observe"),
        ],
        ids=["toggle_off", "no_pr", "no_changes", "observe_purpose"],
    )
    def test_complete_run_does_not_comment(
        self, enable_pr_comments, pr_number, snapshots, baseline_hashes, purpose, github_repo, mock_github_api, mocker
    ):
        if enable_pr_comments:
            github_repo.enable_pr_comments = True
            github_repo.save(update_fields=["enable_pr_comments"])

        # Mock baseline for classification at complete time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=(dict(baseline_hashes), 0),
        )

        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=pr_number,
            snapshots=snapshots,
            baseline_hashes=baseline_hashes,
            purpose=purpose,
        )

        logic.complete_run(run.id)

        assert len(mock_github_api.issue_comments) == 0

    def test_complete_run_posts_error_on_failure(self, github_repo, mock_github_api):
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[],
            baseline_hashes={},
        )

        logic.finish_processing(run.id, error_message="Diff processing failed")

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "error"
        assert "failed" in statuses[-1]["description"].lower()
        assert len(mock_github_api.issue_comments) == 0

    def test_observe_run_with_changes_posts_green_tracking_status(self, github_repo, mock_github_api, mocker):
        # Default-branch (observe) runs are tracking-only: a visual change posts a green,
        # informational status — never a blocking failure — and no review-prompt comment.
        github_repo.enable_pr_comments = True
        github_repo.save(update_fields=["enable_pr_comments"])

        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="master",
            pr_number=None,
            snapshots=[
                {"identifier": "changed", "content_hash": "new_h"},
                {"identifier": "added", "content_hash": "brand_new"},
            ],
            baseline_hashes={"changed": "old_h"},
            purpose="observe",
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"changed": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "Tracking only: 1 changed, 1 new recorded"
        # Observe runs post to a separate, non-gating context. purpose is client-supplied,
        # so greening the gating context would let an observe run bypass branch protection
        # on a PR head SHA — the gating context must never be touched by an observe run.
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (tracking)"
        assert all(s["context"] != "PostHog Visual Review / storybook" for s in statuses)
        assert len(mock_github_api.issue_comments) == 0

    def test_observe_run_without_changes_posts_green_tracking_status(self, github_repo, mock_github_api, mocker):
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="master",
            pr_number=None,
            snapshots=[{"identifier": "snap", "content_hash": "same"}],
            baseline_hashes={"snap": "same"},
            purpose="observe",
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"snap": "same"}, 0),
        )
        logic.complete_run(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert statuses[-1]["description"] == "Tracking only: no visual changes"
        assert statuses[-1]["context"] == "PostHog Visual Review / storybook (tracking)"

    def test_approve_run_posts_success(self, github_repo, mock_github_api, user):
        logic.get_or_create_artifact(repo_id=github_repo.id, content_hash="new_h", storage_path="p/new")
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "snap", "content_hash": "new_h"}],
            baseline_hashes={"snap": "old_h"},
        )
        logic.finish_processing(run.id)

        logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert "approved" in statuses[-1]["description"].lower()

    def test_recompute_does_not_green_approved_but_uncommitted(self, github_repo, mock_github_api, user, mocker):
        # Approving in the DB does not commit the baseline, so recompute must keep the gate red —
        # otherwise re-running CI would re-detect the change. Only finalize (which commits) greens it.
        logic.get_or_create_artifact(repo_id=github_repo.id, content_hash="new_h", storage_path="p/new")
        run, _ = logic.create_run(
            repo_id=github_repo.id,
            team_id=github_repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "snap", "content_hash": "new_h"}],
            baseline_hashes={"snap": "old_h"},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"snap": "old_h"}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)

        logic.approve_snapshots(
            run_id=run.id, user_id=user.id, approved_snapshots=[{"identifier": "snap", "new_hash": "new_h"}]
        )
        logic.recompute_run(run.id, team_id=github_repo.team_id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "failure"
        assert "awaiting commit" in statuses[-1]["description"].lower()

    def test_no_status_without_github_integration(self, team):
        """Status checks are silently skipped when no GitHub integration exists."""
        repo = logic.create_repo(team_id=team.id, repo_external_id=77777, repo_full_name="org/no-github")

        # No mock_github_api/mock_github_integration — should not raise
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": "h1"}],
            baseline_hashes={},
        )

        logic.finish_processing(run.id)

    def test_no_status_without_repo_full_name(self, team, mock_github_integration, mock_github_api):
        """Status checks are silently skipped when repo has no repo_full_name."""
        repo = Repo.objects.create(
            team_id=team.id,
            repo_external_id=88888,
            repo_full_name="",
        )

        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc123",
            branch="main",
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": "h1"}],
            baseline_hashes={},
        )

        logic.finish_processing(run.id)

        assert len(mock_github_api.status_checks) == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunSupersession:
    """When a new run is created for the same (repo, branch, run_type), older runs get superseded."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=66666, repo_full_name="org/test-repo")

    def _create_run(self, repo, *, branch="feat/x", run_type=RunType.STORYBOOK, commit_sha="abc"):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=run_type,
            commit_sha=commit_sha,
            branch=branch,
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": commit_sha}],
            baseline_hashes={},
        )
        logic.finish_processing(run.id)
        run.refresh_from_db()
        return run

    def test_single_run_not_superseded(self, repo):
        run = self._create_run(repo)

        assert run.superseded_by is None
        assert logic.is_run_stale(run) is False

    def test_newer_run_supersedes_older(self, repo):
        old = self._create_run(repo, commit_sha="old")
        new = self._create_run(repo, commit_sha="new")

        old.refresh_from_db()
        assert old.superseded_by_id == new.id
        assert new.superseded_by is None

    def test_supersession_chains(self, repo):
        first = self._create_run(repo, commit_sha="1st")
        second = self._create_run(repo, commit_sha="2nd")
        third = self._create_run(repo, commit_sha="3rd")

        first.refresh_from_db()
        second.refresh_from_db()
        # first was superseded by second, then second by third
        # first still points to second (not updated again)
        assert first.superseded_by_id == second.id
        assert second.superseded_by_id == third.id
        assert third.superseded_by is None

    def test_different_branches_are_independent(self, repo):
        run_a = self._create_run(repo, branch="feat/a", commit_sha="a")
        self._create_run(repo, branch="feat/b", commit_sha="b")

        run_a.refresh_from_db()
        assert run_a.superseded_by is None

    def test_different_run_types_are_independent(self, repo):
        run_sb = self._create_run(repo, run_type=RunType.STORYBOOK, commit_sha="a")
        self._create_run(repo, run_type=RunType.PLAYWRIGHT, commit_sha="b")

        run_sb.refresh_from_db()
        assert run_sb.superseded_by is None

    def test_review_state_filter_excludes_superseded(self, repo, team):
        self._create_run(repo, commit_sha="old")
        self._create_run(repo, commit_sha="new")

        current_runs = list(logic.list_runs_for_team(team.id, review_state="needs_review"))
        stale_runs = list(logic.list_runs_for_team(team.id, review_state="stale"))

        assert len(current_runs) == 1
        assert current_runs[0].commit_sha == "new"
        assert len(stale_runs) == 1
        assert stale_runs[0].commit_sha == "old"

    def test_review_state_counts(self, repo, team):
        self._create_run(repo, commit_sha="old")
        self._create_run(repo, commit_sha="new")

        counts = logic.get_review_state_counts(team.id)

        assert counts["stale"] == 1
        assert counts["needs_review"] == 1

    def test_approve_superseded_run_raises(self, repo, user):
        old = self._create_run(repo, commit_sha="old")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="old", storage_path="p/old")
        self._create_run(repo, commit_sha="new")

        old.refresh_from_db()
        with pytest.raises(logic.StaleRunError):
            logic.finalize_run(run_id=old.id, user_id=user.id, approve_all=True, commit_to_github=False)

    def test_approve_latest_run_succeeds(self, repo, user):
        self._create_run(repo, commit_sha="old")
        newest = self._create_run(repo, commit_sha="new")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="new", storage_path="p/new")

        run = logic.finalize_run(run_id=newest.id, user_id=user.id, approve_all=True, commit_to_github=False)

        assert run.approved is True

    def test_approved_run_superseded_but_stays_clean(self, repo, user, team):
        first = self._create_run(repo, commit_sha="1st")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="1st", storage_path="p/1st")
        logic.finalize_run(run_id=first.id, user_id=user.id, approve_all=True, commit_to_github=False)

        self._create_run(repo, commit_sha="2nd")

        first.refresh_from_db()
        assert first.superseded_by is not None
        # Approved runs still show in clean filter, not stale
        clean = list(logic.list_runs_for_team(team.id, review_state="clean"))
        assert any(r.id == first.id for r in clean)

    def test_clean_run_superseded_but_stays_clean(self, repo, team, mocker):
        clean_run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="clean",
            branch="feat/x",
            pr_number=1,
            snapshots=[{"identifier": "snap", "content_hash": "same"}],
            baseline_hashes={"snap": "same"},
        )

        # Classification happens at complete_run time
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=({"snap": "same"}, 0),
        )
        logic.complete_run(clean_run.id)

        self._create_run(repo, commit_sha="next")

        clean_run.refresh_from_db()
        assert clean_run.superseded_by is not None
        # Clean runs still show in clean filter, not stale
        clean = list(logic.list_runs_for_team(team.id, review_state="clean"))
        assert any(r.id == clean_run.id for r in clean)

    def test_approved_run_shows_in_clean_not_stale(self, repo, team, user):
        first = self._create_run(repo, commit_sha="1st")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="1st", storage_path="p/1st")
        logic.finalize_run(run_id=first.id, user_id=user.id, approve_all=True, commit_to_github=False)

        self._create_run(repo, commit_sha="2nd")

        stale = list(logic.list_runs_for_team(team.id, review_state="stale"))
        clean = list(logic.list_runs_for_team(team.id, review_state="clean"))

        assert len(stale) == 0
        clean_shas = {r.commit_sha for r in clean}
        assert "1st" in clean_shas


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineStamping:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99996, repo_full_name="org/test-quarantine")

    def _create_completed_run(self, repo, mocker, identifiers_and_hashes, baseline=None):
        """Create a run, classify against baseline, and finalize it.

        identifiers_and_hashes: list of (identifier, content_hash)
        baseline: dict of identifier -> baseline_hash (for _resolve_baselines mock)
        """
        snapshots = [{"identifier": ident, "content_hash": h} for ident, h in identifiers_and_hashes]
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=1,
            snapshots=snapshots,
        )

        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=(baseline or {}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        return run

    def test_finish_processing_stamps_quarantined_snapshots(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[
                ("Button-primary", "h1"),
                ("Button-secondary", "h2"),
                ("Card-default", "h3"),
            ],
            baseline={"Button-primary": "old1", "Button-secondary": "old2", "Card-default": "old3"},
        )

        # Quarantine one identifier
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        logic.finish_processing(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["Button-primary"].is_quarantined is True
        assert snapshots["Button-secondary"].is_quarantined is False
        assert snapshots["Card-default"].is_quarantined is False

    def test_unquarantine_clears_flag_on_approve(self, repo, team, user, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        # Create quarantine entry
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button-primary", "h1")],
            baseline={"Button-primary": "old1"},
        )

        logic.finish_processing(run.id)
        snapshot = run.snapshots.get(identifier="Button-primary")
        assert snapshot.is_quarantined is True

        # Unquarantine the identifier
        logic.unquarantine_identifier(
            repo_id=repo.id, identifier="Button-primary", run_type=RunType.STORYBOOK, team_id=team.id
        )

        # Finalize the run — _stamp_quarantine re-evaluates
        logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        snapshot.refresh_from_db()
        assert snapshot.is_quarantined is False

    def test_quarantine_excludes_from_changed_count(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        # Quarantine one identifier before finalization
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button-primary",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[
                ("Button-primary", "h1"),
                ("Button-secondary", "h2"),
                ("Card-new", "h3"),
            ],
            baseline={"Button-primary": "old1", "Button-secondary": "old2"},
        )

        processed = logic.finish_processing(run.id)

        # Button-primary is quarantined — should not count toward changed
        # Button-secondary is changed (not quarantined), Card-new is new (not quarantined)
        assert processed.changed_count == 1  # only Button-secondary
        assert processed.new_count == 1  # only Card-new


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestQuarantineIdentifier:
    """Coverage for `logic.quarantine_identifier` — especially the new
    `source_run_id` behavior (valid run is stored, foreign run is dropped)."""

    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=88888, repo_full_name="org/test-source-run")

    def _mk_run(self, repo: Repo, branch: str = "main") -> Run:
        return Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch=branch,
            commit_sha="abc123",
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

    def test_stores_valid_source_run(self, repo, team, user):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._mk_run(repo)
        entry = logic.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            source_run_id=run.id,
        )
        # Returned row points at the source run …
        assert entry.source_run_id == run.id
        # … and the persisted row agrees.
        persisted = QuarantinedIdentifier.objects.get(id=entry.id)
        assert persisted.source_run_id == run.id

    def test_drops_source_run_from_another_team(self, repo, team, user):
        """A `source_run_id` from a run that doesn't belong to this team/repo
        is silently dropped — the quarantine still gets created, just without
        the cross-team pointer."""
        from posthog.models.team.team import Team

        # Sibling team in the same org with its own repo + run.
        other_team = Team.objects.create(organization=team.organization, name="other")
        other_repo = logic.create_repo(team_id=other_team.id, repo_external_id=12121, repo_full_name="org/other-repo")
        foreign_run = Run.objects.create(
            team_id=other_team.id,
            repo=other_repo,
            run_type=RunType.STORYBOOK,
            branch="main",
            commit_sha="xyz789",
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        entry = logic.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
            source_run_id=foreign_run.id,
        )
        assert entry.source_run_id is None

    def test_omitting_source_run_leaves_it_null(self, repo, team, user):
        entry = logic.quarantine_identifier(
            repo_id=repo.id,
            identifier="flake",
            run_type=RunType.STORYBOOK,
            reason="non-deterministic",
            user_id=user.id,
            team_id=team.id,
        )
        assert entry.source_run_id is None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRecomputeRun:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=77777, repo_full_name="org/test-repo")

    def _create_completed_run(self, repo, mocker, identifiers_and_hashes, baseline=None, metadata=None):
        snapshots = [{"identifier": ident, "content_hash": h} for ident, h in identifiers_and_hashes]
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="my-branch",
            pr_number=1,
            snapshots=snapshots,
            metadata=metadata or {},
        )
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_with_merge_base",
            return_value=(baseline or {}, 0),
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        mocker.patch("products.visual_review.backend.logic._post_commit_status")
        logic.complete_run(run.id)
        logic.finish_processing(run.id)
        run.refresh_from_db()
        return run

    def test_recompute_run_updates_counts_after_quarantine(self, repo, team, mocker):
        from products.visual_review.backend.models import QuarantinedIdentifier

        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1"), ("Card", "h2")],
            baseline={"Button": "old1", "Card": "old2"},
        )
        assert run.changed_count == 2

        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Button",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )
        QuarantinedIdentifier.objects.create(
            repo=repo,
            team_id=team.id,
            identifier="Card",
            run_type=RunType.STORYBOOK,
            reason="flaky",
        )

        result = logic.recompute_run(run.id, team_id=team.id)

        assert result["counts_changed"] is True
        run.refresh_from_db()
        assert run.changed_count == 0

    def test_recompute_run_no_change_without_quarantine(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )

        result = logic.recompute_run(run.id, team_id=team.id)

        assert result["counts_changed"] is False
        assert "CI job ID not available" in result["ci_rerun_error"]

    def test_recompute_run_rejects_non_completed_run(self, repo, team, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=1,
            snapshots=[],
        )

        with pytest.raises(ValueError, match="Can only recompute completed runs"):
            logic.recompute_run(run.id, team_id=team.id)

    def test_recompute_run_rejects_approved_run(self, repo, team, user, mocker):
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )
        logic.finalize_run(run_id=run.id, user_id=user.id, approve_all=True, commit_to_github=False)

        with pytest.raises(ValueError, match="already approved"):
            logic.recompute_run(run.id, team_id=team.id)

    def test_recompute_run_reports_missing_ci_metadata(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
        )

        result = logic.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is False
        assert "CI job ID not available" in result["ci_rerun_error"]

    def test_recompute_run_triggers_ci_rerun(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
            metadata={"github_check_run_id": "72855643533"},
        )

        mocker.patch(
            "products.visual_review.backend.logic._rerun_github_job",
            return_value=(True, None),
        )

        result = logic.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is True
        assert result["ci_rerun_error"] is None

    def test_recompute_run_handles_ci_rerun_failure(self, repo, team, mocker):
        run = self._create_completed_run(
            repo,
            mocker,
            identifiers_and_hashes=[("Button", "h1")],
            baseline={"Button": "old1"},
            metadata={"github_check_run_id": "72855643533"},
        )

        mocker.patch(
            "products.visual_review.backend.logic._rerun_github_job",
            return_value=(False, "GitHub API returned 403 when rerunning job"),
        )

        result = logic.recompute_run(run.id, team_id=team.id)

        assert result["ci_rerun_triggered"] is False
        assert "403" in result["ci_rerun_error"]


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRerunGithubJob:
    """Tests for _rerun_github_job SHA validation."""

    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=55555, repo_full_name="org/test-repo")

    def _make_run(self, repo: "Repo", commit_sha: str = "abc123def456", workflow_run_id: str | None = "98765") -> "Run":
        metadata: dict = {"github_check_run_id": "72855643533"}
        if workflow_run_id is not None:
            metadata["github_run_id"] = workflow_run_id
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha=commit_sha,
            branch="feature",
            pr_number=1,
            snapshots=[],
            metadata=metadata,
        )
        return run

    def test_rejects_non_digit_check_run_id(self, repo):
        run = self._make_run(repo)
        success, error = logic._rerun_github_job(run, "not-a-number")
        assert success is False
        assert error == "Invalid check run ID"

    def test_rejects_when_workflow_run_id_missing(self, repo):
        run = self._make_run(repo, workflow_run_id=None)
        success, error = logic._rerun_github_job(run, "72855643533")
        assert success is False
        assert error == "Workflow run ID not recorded for this run"

    def test_rejects_when_sha_does_not_match(self, repo, mocker):
        run = self._make_run(repo, commit_sha="abc123")
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"head_sha": "different_sha_entirely", "run_id": 98765}
        mocker.patch("products.visual_review.backend.logic._github_api_request", return_value=mock_response)

        success, error = logic._rerun_github_job(run, "72855643533")

        assert success is False
        assert error == "Check run does not belong to this commit"

    def test_rejects_when_workflow_run_does_not_match(self, repo, mocker):
        commit_sha = "abc123def456"
        run = self._make_run(repo, commit_sha=commit_sha, workflow_run_id="98765")
        mock_response = mocker.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"head_sha": commit_sha, "run_id": 11111}
        mocker.patch("products.visual_review.backend.logic._github_api_request", return_value=mock_response)

        success, error = logic._rerun_github_job(run, "72855643533")

        assert success is False
        assert error == "CI job does not belong to this run's workflow"

    def test_rejects_when_check_run_fetch_fails(self, repo, mocker):
        run = self._make_run(repo)
        mock_response = mocker.MagicMock()
        mock_response.status_code = 404
        mocker.patch("products.visual_review.backend.logic._github_api_request", return_value=mock_response)

        success, error = logic._rerun_github_job(run, "72855643533")

        assert success is False
        assert error is not None
        assert "404" in error

    def test_triggers_rerun_when_sha_and_workflow_match(self, repo, mocker):
        commit_sha = "abc123def456"
        run = self._make_run(repo, commit_sha=commit_sha, workflow_run_id="98765")

        job_response = mocker.MagicMock()
        job_response.status_code = 200
        job_response.json.return_value = {"head_sha": commit_sha, "run_id": 98765}

        rerun_response = mocker.MagicMock()
        rerun_response.status_code = 201

        mocker.patch(
            "products.visual_review.backend.logic._github_api_request",
            side_effect=[job_response, rerun_response],
        )

        success, error = logic._rerun_github_job(run, "72855643533")

        assert success is True
        assert error is None


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunIsOnDefaultBranch:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=1234, repo_full_name="org/test-repo")

    def _mock_github(self, mocker, default_branch="master"):
        mock_github = mocker.MagicMock()
        mock_github.access_token_expired.return_value = False
        mocker.patch("products.visual_review.backend.logic.get_github_integration_for_repo", return_value=mock_github)
        mocker.patch("products.visual_review.backend.logic._get_default_branch", return_value=default_branch)

    def test_true_when_branch_matches_default(self, repo, mocker):
        self._mock_github(mocker, default_branch="main")
        assert logic._run_is_on_default_branch(repo, "main") is True

    def test_false_when_branch_differs(self, repo, mocker):
        self._mock_github(mocker, default_branch="main")
        assert logic._run_is_on_default_branch(repo, "feature-x") is False

    def test_false_when_no_github_integration(self, repo, mocker):
        mocker.patch(
            "products.visual_review.backend.logic.get_github_integration_for_repo",
            side_effect=logic.GitHubIntegrationNotFoundError("none"),
        )
        assert logic._run_is_on_default_branch(repo, "master") is False


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestMergeBaseBaselineHealing:
    """Tests for _resolve_baselines_with_merge_base healing rebase-corrupted baselines."""

    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test-repo")

    def _mock_github(
        self,
        mocker,
        branch_baseline,
        merge_base_baseline=None,
        merge_base_sha="abc123",
        default_branch="master",
        commit_sha_baselines=None,
    ):
        mock_github = mocker.MagicMock()
        mock_github.integration.sensitive_config = {"access_token": "fake"}
        mock_github.access_token_expired.return_value = False
        mocker.patch("products.visual_review.backend.logic.get_github_integration_for_repo", return_value=mock_github)

        _commit_sha_baselines = commit_sha_baselines or {}

        def fake_fetch(github, repo_full_name, file_path, ref):
            if ref in _commit_sha_baselines:
                return {k: {"hash": v} for k, v in _commit_sha_baselines[ref].items()}, f"sha-{ref}"
            if ref in ("my-branch", default_branch):
                return {k: {"hash": v} for k, v in branch_baseline.items()}, "sha1"
            if ref == merge_base_sha:
                baselines = merge_base_baseline if merge_base_baseline is not None else branch_baseline
                return {k: {"hash": v} for k, v in baselines.items()}, "sha2"
            return {}, None

        mocker.patch("products.visual_review.backend.logic._fetch_baseline_file", side_effect=fake_fetch)
        mocker.patch("products.visual_review.backend.logic._get_merge_base_sha", return_value=merge_base_sha)
        mocker.patch("products.visual_review.backend.logic._get_default_branch", return_value=default_branch)
        mocker.patch(
            "products.visual_review.backend.logic._verify_baseline_hashes", side_effect=lambda repo, hashes: hashes
        )
        return mock_github

    def test_no_healing_when_baselines_match(self, repo, mocker):
        baseline = {"A": "h1", "B": "h2"}
        self._mock_github(mocker, branch_baseline=baseline, merge_base_baseline=baseline)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == baseline
        assert healed == 0

    def test_heals_entries_missing_from_branch(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        merge_base_baseline = {"A": "h1", "B": "h2", "C": "h3"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == {"A": "h1", "B": "h2", "C": "h3"}
        assert healed == 2

    def test_branch_wins_on_conflict(self, repo, mocker):
        branch_baseline = {"A": "branch_hash"}
        merge_base_baseline = {"A": "master_hash", "B": "h2"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged["A"] == "branch_hash"
        assert merged["B"] == "h2"
        assert healed == 1

    def test_branch_approvals_preserved(self, repo, mocker):
        branch_baseline = {"A": "h1", "NewStory": "new_hash"}
        merge_base_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert "NewStory" in merged
        assert merged["NewStory"] == "new_hash"
        assert healed == 0

    def test_skips_merge_base_for_default_branch(self, repo, mocker):
        baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=baseline, default_branch="master")

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "master")

        assert merged == baseline
        assert healed == 0

    @pytest.mark.parametrize(
        "commit_sha, expected_baseline",
        [
            ("deadbeef", {"A": "h1"}),  # pinned to commit SHA
            (None, {"A": "h1", "B": "h2"}),  # falls back to branch tip
        ],
    )
    def test_default_branch_baseline_ref(self, repo, mocker, commit_sha, expected_baseline):
        """Baseline is pinned to commit SHA when provided, otherwise falls back to branch tip."""
        branch_tip_baseline = {"A": "h1", "B": "h2"}
        commit_baseline = {"A": "h1"}
        self._mock_github(
            mocker,
            branch_baseline=branch_tip_baseline,
            default_branch="master",
            commit_sha_baselines={"deadbeef": commit_baseline},
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "master", commit_sha=commit_sha)

        assert merged == expected_baseline
        assert healed == 0

    def test_non_default_branch_ignores_commit_sha(self, repo, mocker):
        """On non-default branches, commit_sha is ignored — branch name is used."""
        branch_baseline = {"A": "h1"}
        merge_base_baseline = {"A": "h1", "C": "h3"}
        commit_baseline = {"X": "hx"}  # Should NOT be used
        self._mock_github(
            mocker,
            branch_baseline=branch_baseline,
            merge_base_baseline=merge_base_baseline,
            commit_sha_baselines={"deadbeef": commit_baseline},
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch", commit_sha="deadbeef")

        # Should use branch baseline + merge-base healing, NOT the commit baseline
        assert merged == {"A": "h1", "C": "h3"}
        assert healed == 1

    def test_falls_back_on_merge_base_failure(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_sha=None)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == branch_baseline
        assert healed == 0

    def test_falls_back_when_merge_base_file_fetch_raises(self, repo, mocker):
        branch_baseline = {"A": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline={"A": "h1", "B": "h2"})
        mocker.patch(
            "products.visual_review.backend.logic._resolve_baselines_at_ref",
            side_effect=[branch_baseline, Exception("GitHub 500")],
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == branch_baseline
        assert healed == 0

    def test_first_run_both_baselines_empty(self, repo, mocker):
        self._mock_github(mocker, branch_baseline={}, merge_base_baseline={})

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert merged == {}
        assert healed == 0

    def test_heals_rebase_scenario_end_to_end(self, repo, mocker):
        """Simulates Paul's bug: rebase replayed bot commit, dropping 8 entries."""
        branch_baseline = {"story1": "h1", "story2": "h2"}
        merge_base_baseline = {
            "story1": "h1",
            "story2": "h2",
            "lost1": "h3",
            "lost2": "h4",
            "lost3": "h5",
            "lost4": "h6",
            "lost5": "h7",
            "lost6": "h8",
            "lost7": "h9",
            "lost8": "h10",
        }
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        merged, healed = logic._resolve_baselines_with_merge_base(repo, "storybook", "my-branch")

        assert len(merged) == 10
        assert healed == 8
        assert all(f"lost{i}" in merged for i in range(1, 9))

    def test_healing_integrates_with_complete_run(self, repo, mocker):
        """Healed entries classify as unchanged when hashes match."""
        branch_baseline = {"existing": "h1"}
        merge_base_baseline = {"existing": "h1", "healed": "h2"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h2", storage_path="p/h2")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="my-branch",
            pr_number=1,
            snapshots=[
                {"identifier": "existing", "content_hash": "h1"},
                {"identifier": "healed", "content_hash": "h2"},
            ],
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["existing"].result == SnapshotResult.UNCHANGED
        assert snapshots["healed"].result == SnapshotResult.UNCHANGED

        run.refresh_from_db()
        assert run.metadata.get("baseline_healed_from_merge_base") == 1

    def test_default_branch_race_condition_no_false_removals(self, repo, mocker):
        """Reproduces the race where a newer commit advances the baseline on master.

        Scenario: commit A (posthog-js upgrade) lands on master, then commit B
        (trendlines, adding 6 stories) lands right after.  By the time commit A's
        VR run calls complete_run, the branch tip already points at commit B's
        baseline (with 6 extra entries).  Without pinning, VR would report 6
        false "removed" snapshots.  With pinning, it fetches the baseline at
        commit A's SHA and sees 0 removals.
        """
        # Commit A's baseline: 3 stories
        commit_a_baseline = {"story1": "h1", "story2": "h2", "story3": "h3"}
        # Branch tip (after commit B landed): 3 + 6 = 9 stories
        branch_tip_baseline = {
            **commit_a_baseline,
            "new1": "n1",
            "new2": "n2",
            "new3": "n3",
            "new4": "n4",
            "new5": "n5",
            "new6": "n6",
        }
        self._mock_github(
            mocker,
            branch_baseline=branch_tip_baseline,
            default_branch="master",
            commit_sha_baselines={"commit_a_sha": commit_a_baseline},
        )

        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h1", storage_path="p/h1")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h2", storage_path="p/h2")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="h3", storage_path="p/h3")

        # Commit A's run only has the 3 original stories
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="commit_a_sha",
            branch="master",
            pr_number=None,
            snapshots=[
                {"identifier": "story1", "content_hash": "h1"},
                {"identifier": "story2", "content_hash": "h2"},
                {"identifier": "story3", "content_hash": "h3"},
            ],
        )

        logic.complete_run(run.id)

        run.refresh_from_db()
        assert run.removed_count == 0
        assert run.new_count == 0
        assert run.changed_count == 0

    def test_healing_detects_changed_when_hash_differs(self, repo, mocker):
        """Healed entry with different hash shows as changed, not new."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"flaky": "master_hash"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        logic.get_or_create_artifact(repo_id=repo.id, content_hash="master_hash", storage_path="p/master")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="branch_hash", storage_path="p/branch")
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="my-branch",
            pr_number=1,
            snapshots=[{"identifier": "flaky", "content_hash": "branch_hash"}],
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        snapshot = run.snapshots.get(identifier="flaky")
        assert snapshot.result == SnapshotResult.CHANGED
        assert snapshot.baseline_hash == "master_hash"

    @pytest.mark.parametrize(
        "prior_branch, prior_run_type, prior_approved, prior_review_state, expect_tombstoned",
        [
            ("my-branch", RunType.STORYBOOK, True, ReviewState.APPROVED, True),
            ("someone-else", RunType.STORYBOOK, True, ReviewState.APPROVED, False),
            ("my-branch", "playwright", True, ReviewState.APPROVED, False),
            ("my-branch", RunType.STORYBOOK, False, ReviewState.PENDING, False),
        ],
        ids=["approved_on_branch", "wrong_branch", "wrong_run_type", "not_approved"],
    )
    def test_tombstone_excludes_only_approved_removals_on_branch(
        self, repo, team, mocker, prior_branch, prior_run_type, prior_approved, prior_review_state, expect_tombstoned
    ):
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"candidate": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        prior_run = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=prior_run_type,
            branch=prior_branch,
            commit_sha="prior-sha",
            status=RunStatus.COMPLETED,
            approved=prior_approved,
        )
        RunSnapshot.objects.create(
            run=prior_run,
            team_id=team.id,
            identifier="candidate",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=prior_review_state,
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, "my-branch")

        if expect_tombstoned:
            assert merged == {}
            assert healed == 0
        else:
            assert merged == merge_base_baseline
            assert healed == 1

    def test_tombstone_cleared_by_later_re_addition(self, repo, team, mocker):
        """Remove→approve→restore→approve: the re-addition clears the tombstone."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"story-x": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        # Run 1: story-x removed and approved
        run1 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha1",
            status=RunStatus.COMPLETED,
            approved=True,
            created_at=timezone.now() - timedelta(hours=2),
        )
        RunSnapshot.objects.create(
            run=run1,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=ReviewState.APPROVED,
        )

        # Supersede run1 (as create_run would)
        run1.superseded_by = run1
        run1.save(update_fields=["superseded_by"])

        # Run 2: story-x re-added and approved as NEW
        run2 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha2",
            status=RunStatus.COMPLETED,
            approved=True,
            created_at=timezone.now() - timedelta(hours=1),
        )
        RunSnapshot.objects.create(
            run=run2,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="",
            current_hash="h1",
            result=SnapshotResult.NEW,
            review_state=ReviewState.APPROVED,
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, "my-branch")

        # Latest approved outcome is NEW, not REMOVED — tombstone cleared, healing works
        assert "story-x" in merged
        assert healed == 1

    def test_tombstone_persists_without_later_approval(self, repo, team, mocker):
        """Remove→approve: tombstone stays until a later approval overrides it."""
        branch_baseline: dict[str, str] = {}
        merge_base_baseline = {"story-x": "h1"}
        self._mock_github(mocker, branch_baseline=branch_baseline, merge_base_baseline=merge_base_baseline)

        run1 = Run.objects.create(
            team_id=team.id,
            repo=repo,
            run_type=RunType.STORYBOOK,
            branch="my-branch",
            commit_sha="sha1",
            status=RunStatus.COMPLETED,
            approved=True,
        )
        RunSnapshot.objects.create(
            run=run1,
            team_id=team.id,
            identifier="story-x",
            baseline_hash="h1",
            current_hash="",
            result=SnapshotResult.REMOVED,
            review_state=ReviewState.APPROVED,
        )

        merged, healed = logic._resolve_baselines_with_merge_base(repo, RunType.STORYBOOK, "my-branch")

        assert "story-x" not in merged
        assert healed == 0


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestVerifyUploadsAndCreateArtifacts:
    """Server-side hash integrity for uploaded PNGs."""

    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=42424, repo_full_name="org/vr")

    def _png(self, color: tuple[int, int, int, int]) -> bytes:
        import io as _io

        from PIL import Image as _Image

        img = _Image.new("RGBA", (8, 8), color)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_creates_artifact_with_server_computed_hash(self, repo, mocker):
        from products.visual_review.backend.hashing import hash_image

        png = self._png((10, 20, 30, 255))
        server_hash = hash_image(png)

        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="sha",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Card", "content_hash": server_hash}],
        )

        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            return_value=png,
        )

        created = logic.verify_uploads_and_create_artifacts(run.id)

        assert created == 1
        artifact = logic.get_artifact(repo.id, server_hash)
        assert artifact is not None
        assert artifact.content_hash == server_hash
        assert artifact.size_bytes == len(png)

    def test_hash_mismatch_raises_and_persists_no_artifacts(self, repo, mocker):
        # Two snapshots: first verifies cleanly, second has a mismatched claim.
        # The two-pass split must prevent the first artifact from being written
        # before the second is checked.
        from products.visual_review.backend.hashing import hash_image

        png_a = self._png((255, 0, 0, 255))
        png_b = self._png((0, 0, 255, 255))
        good_hash = hash_image(png_a)
        bad_claim = "f" * 64  # nothing hashes to this

        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="sha",
            branch="main",
            pr_number=None,
            snapshots=[
                {"identifier": "Good", "content_hash": good_hash},
                {"identifier": "Bad", "content_hash": bad_claim},
            ],
        )

        def _read(self, content_hash):
            return {good_hash: png_a, bad_claim: png_b}.get(content_hash)

        mocker.patch("products.visual_review.backend.storage.ArtifactStorage.read", autospec=True, side_effect=_read)

        with pytest.raises(logic.HashIntegrityError):
            logic.verify_uploads_and_create_artifacts(run.id)

        assert logic.get_artifact(repo.id, good_hash) is None
        assert logic.get_artifact(repo.id, bad_claim) is None

    def test_corrupt_png_raises_hash_integrity_error(self, repo, mocker):
        run, _ = logic.create_run(
            repo_id=repo.id,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="sha",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Card", "content_hash": "a" * 64}],
        )

        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            return_value=b"not a png",
        )

        with pytest.raises(logic.HashIntegrityError):
            logic.verify_uploads_and_create_artifacts(run.id)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestVerifyBaselineHashes:
    """Bootstrap-window guard: unsigned baselines must not be honored."""

    def test_drops_all_entries_when_no_signing_keys(self, team):
        repo = Repo.objects.create(
            team_id=team.id,
            repo_external_id=77777,
            repo_full_name="org/no-keys",
            signing_keys={},
        )

        result = logic._verify_baseline_hashes(repo, {"snap-a": "v1.k1.deadbeef.fake"})

        assert result == {}


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestApprovalComment:
    """Tests for the post-approval PR comment summary."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(
            team_id=team.id,
            repo_external_id=66666,
            repo_full_name="test-org/approval-repo",
            enable_pr_comments=True,
        )

    @pytest.fixture
    def run_with_snapshots(self, repo):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="deadbeef",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
            metadata={"github_comment_id": 9001, "baseline_commit_sha": "abc1234567"},
        )

        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Login/Form",
            current_hash="curr_a",
            baseline_hash="base_a",
            result=SnapshotResult.CHANGED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Settings/Tab",
            current_hash="curr_b",
            baseline_hash="",
            result=SnapshotResult.NEW,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Old/Component",
            current_hash="",
            baseline_hash="base_c",
            result=SnapshotResult.REMOVED,
        )

        return run

    def test_build_approval_comment_body_summarizes_changes(self, repo, run_with_snapshots):
        approver = logic._Approver(label="alice", is_github_login=True)
        body = logic._build_approval_comment_body(run_with_snapshots, repo, approver)

        assert "✅ **Visual changes approved** by @alice" in body
        assert "abc1234" in body  # baseline SHA prefix
        assert f"/visual_review/runs/{run_with_snapshots.id}" in body
        assert "1 changed, 1 new, 1 removed." in body
        assert "<img" not in body
        assert "<table" not in body
        assert "/api/visual_review/public/" not in body

    def test_build_approval_comment_body_falls_back_to_a_reviewer(self, repo, run_with_snapshots):
        body = logic._build_approval_comment_body(run_with_snapshots, repo, None)

        assert "by a reviewer" in body

    def test_build_approval_comment_body_escapes_non_github_approver(self, repo, run_with_snapshots):
        # email local-part / first_name fallbacks are user-controlled — must be escaped
        approver = logic._Approver(label="alice[evil](http://attacker)", is_github_login=False)
        body = logic._build_approval_comment_body(run_with_snapshots, repo, approver)

        # No raw `@` mention (which would render as a GitHub user link)
        assert "by @alice" not in body
        # Markdown control chars in the label must be backslash-escaped
        assert "\\[evil\\]" in body
        assert "\\(http://attacker\\)" in body

    def test_build_approval_comment_body_no_actionable_snapshots(self, repo):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="empty",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        approver = logic._Approver(label="bob", is_github_login=True)
        body = logic._build_approval_comment_body(run, repo, approver)
        assert "✅ **Visual changes approved**" in body
        # No counts line when there's nothing to summarize
        assert "changed" not in body
        assert "new" not in body
        assert "removed" not in body
        # A genuinely empty run stays silent — the suppressed-only note must not fire
        assert "quarantined or tolerated" not in body

    def test_build_approval_comment_body_excludes_quarantined_and_tolerated(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="mixed",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id, run=run, identifier="Real/Change", result=SnapshotResult.CHANGED
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Known/Tolerated",
            result=SnapshotResult.NEW,
            review_state=ReviewState.TOLERATED,
        )

        body = logic._build_approval_comment_body(run, repo, logic._Approver(label="bob", is_github_login=True))

        assert "1 changed." in body
        assert "new" not in body
        assert "quarantined or tolerated" not in body

    def test_build_approval_comment_body_notes_when_only_quarantined_and_tolerated(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="suppressed",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Known/Tolerated",
            result=SnapshotResult.NEW,
            review_state=ReviewState.TOLERATED,
        )

        body = logic._build_approval_comment_body(run, repo, logic._Approver(label="bob", is_github_login=True))

        assert "All visual changes in this run were quarantined or tolerated." in body
        assert "1 changed" not in body

    def test_post_approval_comment_skips_when_pr_comments_disabled(self, repo, run_with_snapshots, mocker):
        repo.enable_pr_comments = False
        repo.save(update_fields=["enable_pr_comments"])

        spy = mocker.patch.object(logic, "_github_api_request")
        logic._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_when_no_pr_number(self, repo, run_with_snapshots, mocker):
        run_with_snapshots.pr_number = None
        run_with_snapshots.save(update_fields=["pr_number"])

        spy = mocker.patch.object(logic, "_github_api_request")
        logic._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_for_non_human_decision(self, repo, run_with_snapshots, mocker):
        from products.visual_review.backend.facade.enums import ReviewDecision

        run_with_snapshots.review_decision = ReviewDecision.AUTO_APPROVED
        run_with_snapshots.save(update_fields=["review_decision"])

        spy = mocker.patch.object(logic, "_github_api_request")
        logic._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_skips_when_no_existing_comment_id(self, repo, run_with_snapshots, mocker):
        run_with_snapshots.metadata = {}
        run_with_snapshots.save(update_fields=["metadata"])

        spy = mocker.patch.object(logic, "_github_api_request")
        logic._post_approval_comment(run_with_snapshots, repo)
        spy.assert_not_called()

    def test_post_approval_comment_patches_existing_comment(self, repo, run_with_snapshots, mocker):
        class FakeResp:
            status_code = 200
            text = ""

        spy = mocker.patch.object(logic, "_github_api_request", return_value=FakeResp())

        logic._post_approval_comment(run_with_snapshots, repo)

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["method"] == "PATCH"
        assert kwargs["path"] == "issues/comments/9001"
        assert "✅ **Visual changes approved**" in kwargs["json"]["body"]

    def test_post_approval_comment_falls_back_to_post_on_404(self, repo, run_with_snapshots, mocker):
        class PatchResp:
            status_code = 404
            text = "Not Found"

        class PostResp:
            status_code = 201
            text = ""

            @staticmethod
            def json():
                return {"id": 9999}

        spy = mocker.patch.object(logic, "_github_api_request", side_effect=[PatchResp(), PostResp()])

        logic._post_approval_comment(run_with_snapshots, repo)

        assert spy.call_count == 2
        first_call = spy.call_args_list[0].kwargs
        second_call = spy.call_args_list[1].kwargs
        assert first_call["method"] == "PATCH"
        assert second_call["method"] == "POST"
        assert second_call["path"] == "issues/42/comments"

        run_with_snapshots.refresh_from_db()
        assert run_with_snapshots.metadata["github_comment_id"] == 9999

    def test_post_approval_comment_swallows_exceptions(self, repo, run_with_snapshots, mocker):
        mocker.patch.object(logic, "_github_api_request", side_effect=RuntimeError("boom"))
        # Must not raise
        logic._post_approval_comment(run_with_snapshots, repo)

    @staticmethod
    def _mk_artifact(repo, content_hash, *, with_thumbnail=None):
        from products.visual_review.backend.models import Artifact

        artifact = Artifact.objects.create(
            repo=repo,
            team_id=repo.team_id,
            content_hash=content_hash,
            storage_path=f"path/{content_hash}",
            width=320,
            height=200,
        )
        if with_thumbnail:
            thumb = Artifact.objects.create(
                repo=repo,
                team_id=repo.team_id,
                content_hash=with_thumbnail,
                storage_path=f"thumb/{with_thumbnail}",
            )
            artifact.thumbnail = thumb
            artifact.save(update_fields=["thumbnail"])
        return artifact

    @staticmethod
    def _fake_storage(returns_url=True):
        class _FakeStorage:
            def __init__(self, repo_id):
                self.repo_id = repo_id

            def get_presigned_download_url(self, content_hash, expiration=3600):
                return f"https://cdn.example/{content_hash}?exp={expiration}" if returns_url else None

        return _FakeStorage

    @pytest.fixture
    def run_with_artifacts(self, repo):
        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="cafef00d",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
            metadata={"github_comment_id": 9001},
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Login/Form",
            result=SnapshotResult.CHANGED,
            baseline_artifact=self._mk_artifact(repo, "base_a", with_thumbnail="thumb_a"),
            current_artifact=self._mk_artifact(repo, "curr_a"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Settings/Tab",
            result=SnapshotResult.NEW,
            current_artifact=self._mk_artifact(repo, "curr_b"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run,
            identifier="Old/Component",
            result=SnapshotResult.REMOVED,
            baseline_artifact=self._mk_artifact(repo, "base_c"),
        )
        return run

    def test_build_approval_comment_body_includes_before_after_tables(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())

        body = logic._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        # Changed table: baseline before, current after — full-resolution originals,
        # not thumbnails, so clicking opens the image at full size
        assert "**Changed**" in body
        assert "| Snapshot | Before | After |" in body
        assert "https://cdn.example/base_a" in body  # full-res original, not thumb_a
        assert "https://cdn.example/thumb_a" not in body
        assert "https://cdn.example/curr_a" in body
        # Removed snapshot lives in the changed table with an empty after cell
        assert "_(removed)_" in body
        assert "https://cdn.example/base_c" in body
        # New table: empty before cell, current after
        assert "**New**" in body
        assert "https://cdn.example/curr_b" in body
        assert "_(none)_" in body
        # Long-lived URL so GitHub's image proxy can still fetch it later
        assert f"exp={logic._COMMENT_IMAGE_URL_EXPIRATION}" in body

    def test_build_snapshot_image_tables_excludes_quarantined_and_tolerated(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run_with_artifacts,
            identifier="Flaky/Quarantined",
            result=SnapshotResult.CHANGED,
            is_quarantined=True,
            baseline_artifact=self._mk_artifact(repo, "base_q"),
            current_artifact=self._mk_artifact(repo, "curr_q"),
        )
        RunSnapshot.objects.create(
            team_id=repo.team_id,
            run=run_with_artifacts,
            identifier="Known/Tolerated",
            result=SnapshotResult.CHANGED,
            review_state=ReviewState.TOLERATED,
            baseline_artifact=self._mk_artifact(repo, "base_t"),
            current_artifact=self._mk_artifact(repo, "curr_t"),
        )

        body = logic._build_snapshot_image_tables(run_with_artifacts, repo)

        assert "Flaky/Quarantined" not in body
        assert "Known/Tolerated" not in body
        assert "curr_q" not in body
        assert "curr_t" not in body
        assert "Login/Form" in body

    def test_build_approval_comment_body_deep_links_each_snapshot(self, repo, run_with_artifacts, mocker):
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())

        body = logic._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        # Each snapshot name links straight to its deep link on the run page
        changed = run_with_artifacts.snapshots.get(identifier="Login/Form")
        assert f"[`Login/Form`]({logic._run_url(run_with_artifacts, repo)}?snapshot={changed.id})" in body

    def test_build_approval_comment_body_caps_at_eight_and_links_out(self, repo, mocker):
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())

        run = Run.objects.create(
            team_id=repo.team_id,
            repo=repo,
            commit_sha="manysnaps",
            branch="feature",
            pr_number=42,
            review_decision=ReviewDecision.HUMAN_APPROVED,
        )
        for i in range(11):
            RunSnapshot.objects.create(
                team_id=repo.team_id,
                run=run,
                identifier=f"Story/{i:02d}",
                result=SnapshotResult.CHANGED,
                baseline_artifact=self._mk_artifact(repo, f"base_{i}"),
                current_artifact=self._mk_artifact(repo, f"curr_{i}"),
            )

        body = logic._build_approval_comment_body(run, repo, None, add_images=True)

        # 8 of 11 rows rendered, the rest linked out
        assert body.count("<img") == 8 * 2  # before + after per shown row
        assert "…and 3 more" in body
        assert f"/visual_review/runs/{run.id})" in body

    def test_build_approval_comment_body_falls_back_to_text_without_storage(self, repo, run_with_artifacts, mocker):
        # Images requested, but storage yields no URL — fall back to the text summary.
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage(returns_url=False))

        body = logic._build_approval_comment_body(run_with_artifacts, repo, None, add_images=True)

        assert "<img" not in body
        assert "**Changed**" not in body
        # Still carries the textual summary
        assert "1 changed, 1 new, 1 removed." in body

    def test_build_approval_comment_body_omits_images_unless_opted_in(self, repo, run_with_artifacts, mocker):
        # add_images defaults false: the comment is always posted but stays a text summary.
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())

        body = logic._build_approval_comment_body(run_with_artifacts, repo, None)

        assert "<img" not in body
        assert "**Changed**" not in body
        # The comment still summarizes what changed and links to the run
        assert "1 changed, 1 new, 1 removed." in body
        assert f"/visual_review/runs/{run_with_artifacts.id}" in body

    def test_image_cell_escapes_alt_and_src(self):
        # Both attributes are escaped so a quote in either can't break out of the tag
        cell = logic._image_cell('https://cdn.example/x?a="b', 'a"b')
        assert 'alt="a&quot;b"' in cell
        assert 'src="https://cdn.example/x?a=&quot;b"' in cell

    def test_image_cell_constrains_width_but_serves_full_resolution(self):
        # The cell shows a width-constrained image whose src is the full-resolution
        # original, so GitHub opens it at full size when clicked — no <a> wrapper needed.
        cell = logic._image_cell("https://cdn.example/full", "after")
        assert cell == f'<img src="https://cdn.example/full" width="{logic._COMMENT_IMAGE_WIDTH}" alt="after">'

    @pytest.mark.parametrize(
        "identifier,expected",
        [
            ("a|b", "`a\\|b`"),  # pipes escaped so the cell stays intact
            ("a`b", "`ab`"),  # backticks stripped so the code span isn't closed early
        ],
    )
    def test_snapshot_name_cell_escapes_markdown(self, identifier, expected):
        assert logic._snapshot_name_cell(identifier) == expected

    def test_snapshot_name_cell_collapses_control_characters(self):
        # Newlines/tabs/carriage returns would otherwise break out of the table row
        cell = logic._snapshot_name_cell("a\nb\tc\rd")
        assert "\n" not in cell
        assert "\r" not in cell
        assert "\t" not in cell
        assert cell == "`a b c d`"

    def test_snapshot_name_cell_newline_cannot_inject_table_rows(self):
        # A pipe-laden payload across a newline stays a single escaped cell
        cell = logic._snapshot_name_cell("x\n| --- |")
        assert "\n" not in cell
        assert cell == "`x \\| --- \\|`"

    def test_comment_image_url_requests_seven_day_expiry(self, repo, mocker):
        # The 7-day expiry is load-bearing: GitHub's image proxy may fetch the URL
        # long after the comment is posted, so lock the behaviour with a test.
        captured = {}

        class _RecordingStorage:
            def __init__(self, repo_id):
                pass

            def get_presigned_download_url(self, content_hash, expiration=3600):
                captured["content_hash"] = content_hash
                captured["expiration"] = expiration
                return "https://cdn.example/x"

        mocker.patch.object(logic, "ArtifactStorage", _RecordingStorage)

        artifact = self._mk_artifact(repo, "h1")
        url = logic._comment_image_url(repo, artifact)

        assert url == "https://cdn.example/x"
        assert captured["content_hash"] == "h1"
        assert captured["expiration"] == 60 * 60 * 24 * 7 == 604800

    def test_comment_image_url_serves_full_resolution_not_thumbnail(self, repo, mocker):
        # Serve the original artifact, not the thumbnail, so clicking opens it full-size
        mocker.patch.object(logic, "ArtifactStorage", self._fake_storage())

        artifact = self._mk_artifact(repo, "full_h", with_thumbnail="thumb_h")
        url = logic._comment_image_url(repo, artifact)

        assert url is not None
        assert "full_h" in url
        assert "thumb_h" not in url
