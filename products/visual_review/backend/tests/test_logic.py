"""Unit tests for visual_review business logic."""

import pytest

from products.visual_review.backend import logic
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Repo
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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"Button": "baseline_hash"},
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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"unchanged": "same_hash", "changed": "old_hash"},
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
        logic.mark_run_completed(run.id)

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"kept": "h1", "deleted": "h2"},
        )

        completed = logic.complete_run(run.id)

        assert completed.removed_count == 1
        removed = run.snapshots.get(identifier="deleted")
        assert removed.result == SnapshotResult.REMOVED

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
        logic.mark_run_completed(run.id)

        with pytest.raises(ValueError, match="Observational"):
            logic.approve_run(
                run_id=run.id,
                user_id=1,
                approved_snapshots=[{"identifier": "btn", "new_hash": "h1"}],
            )

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

    def test_mark_run_completed_success(self, repo, mocker):
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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"changed1": "old"},
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)

        # complete_run leaves the run in PROCESSING when there are changes;
        # mark_run_completed finalizes it
        updated = logic.mark_run_completed(run.id)

        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.changed_count == 1
        assert updated.new_count == 1
        assert updated.error_message == ""

    def test_mark_run_completed_with_error(self, repo):
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

        updated = logic.mark_run_completed(run.id, error_message="Something failed")

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"Button": "old_hash"},
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.mark_run_completed(run.id)

        updated = logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "Button", "new_hash": "new_hash"}],
        )

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
        mocker.patch("products.visual_review.backend.logic._resolve_baselines", return_value={"Button": "old_hash"})
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.mark_run_completed(run.id)

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
            "products.visual_review.backend.logic._resolve_baselines", return_value={identifier: baseline_hash}
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.mark_run_completed(run.id)
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
        mocker.patch("products.visual_review.backend.logic._resolve_baselines", return_value={"Button": "same"})
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.mark_run_completed(run.id)

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"snap": "same"},
        )
        logic.complete_run(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert "No visual changes" in statuses[-1]["description"]

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"changed": "old_h"},
        )
        mocker.patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
        logic.complete_run(run.id)
        logic.mark_run_completed(run.id)

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
        logic.mark_run_completed(run1.id)

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
        logic.mark_run_completed(run2.id)

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

        logic.mark_run_completed(run.id)
        logic.mark_run_completed(run.id)

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value=dict(baseline_hashes),
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

        logic.mark_run_completed(run.id, error_message="Diff processing failed")

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "error"
        assert "failed" in statuses[-1]["description"].lower()
        assert len(mock_github_api.issue_comments) == 0

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

        logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "snap", "new_hash": "new_h"}],
        )

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert "approved" in statuses[-1]["description"].lower()

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

        logic.mark_run_completed(run.id)

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

        logic.mark_run_completed(run.id)

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
        logic.mark_run_completed(run.id)
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
            logic.approve_run(
                run_id=old.id,
                user_id=user.id,
                approved_snapshots=[{"identifier": "snap", "new_hash": "old"}],
                commit_to_github=False,
            )

    def test_approve_latest_run_succeeds(self, repo, user):
        self._create_run(repo, commit_sha="old")
        newest = self._create_run(repo, commit_sha="new")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="new", storage_path="p/new")

        run = logic.approve_run(
            run_id=newest.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "snap", "new_hash": "new"}],
            commit_to_github=False,
        )

        assert run.approved is True

    def test_approved_run_superseded_but_stays_clean(self, repo, user, team):
        first = self._create_run(repo, commit_sha="1st")
        logic.get_or_create_artifact(repo_id=repo.id, content_hash="1st", storage_path="p/1st")
        logic.approve_run(
            run_id=first.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "snap", "new_hash": "1st"}],
            commit_to_github=False,
        )

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
            "products.visual_review.backend.logic._resolve_baselines",
            return_value={"snap": "same"},
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
        logic.approve_run(
            run_id=first.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "snap", "new_hash": "1st"}],
            commit_to_github=False,
        )

        self._create_run(repo, commit_sha="2nd")

        stale = list(logic.list_runs_for_team(team.id, review_state="stale"))
        clean = list(logic.list_runs_for_team(team.id, review_state="clean"))

        assert len(stale) == 0
        clean_shas = {r.commit_sha for r in clean}
        assert "1st" in clean_shas
