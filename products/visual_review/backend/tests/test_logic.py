"""Unit tests for visual_review business logic."""

import pytest

from products.visual_review.backend import logic
from products.visual_review.backend.facade.enums import RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Repo


@pytest.mark.django_db
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


@pytest.mark.django_db
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


@pytest.mark.django_db
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

    def test_create_run_with_baselines(self, repo):
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

        snapshot = run.snapshots.first()
        assert snapshot is not None
        assert snapshot.baseline_artifact_id == baseline_artifact.id
        assert snapshot.result == SnapshotResult.CHANGED

    def test_create_run_snapshot_results(self, repo):
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

        snapshots = {s.identifier: s for s in run.snapshots.all()}
        assert snapshots["unchanged"].result == SnapshotResult.UNCHANGED
        assert snapshots["new"].result == SnapshotResult.NEW
        assert snapshots["changed"].result == SnapshotResult.CHANGED

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

    def test_mark_run_completed_success(self, repo):
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


@pytest.mark.django_db
class TestApproveRun:
    @pytest.fixture
    def repo(self, team):
        return logic.create_repo(team_id=team.id, repo_external_id=99999, repo_full_name="org/test")

    def test_approve_run(self, repo, user):
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

        updated = logic.approve_run(
            run_id=run.id,
            user_id=user.id,
            approved_snapshots=[{"identifier": "Button", "new_hash": "new_hash"}],
        )

        assert updated.approved is True
        assert updated.approved_at is not None
        assert updated.approved_by_id == user.id

        # Result should NOT be mutated - approval is recorded separately
        snapshot = updated.snapshots.first()
        assert snapshot is not None
        assert snapshot.result == SnapshotResult.CHANGED  # Result preserved
        assert snapshot.approved_hash == "new_hash"  # Approval recorded
        assert snapshot.reviewed_at is not None
        assert snapshot.reviewed_by_id == user.id


@pytest.mark.django_db
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


@pytest.mark.django_db(transaction=True)
class TestCommitStatusChecks:
    """Test that GitHub commit status checks are posted at state transitions."""

    @pytest.fixture
    def github_repo(self, team, mock_github_integration):
        return Repo.objects.create(
            team=team,
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

    def test_complete_run_posts_success_when_no_changes(self, github_repo, mock_github_api):
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

        logic.mark_run_completed(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "success"
        assert "No visual changes" in statuses[-1]["description"]

    def test_complete_run_posts_failure_when_changes_detected(self, github_repo, mock_github_api):
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

        logic.mark_run_completed(run.id)

        statuses = mock_github_api.status_checks
        assert statuses[-1]["state"] == "failure"
        assert "1 changed" in statuses[-1]["description"]
        assert "1 new" in statuses[-1]["description"]

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
            commit_to_github=False,
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
            team=team,
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


@pytest.mark.django_db
class TestRunSupersession:
    """When a new run is created for the same (repo, branch, run_type), older runs get superseded."""

    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team=team, repo_external_id=66666, repo_full_name="org/test-repo")

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

    def test_clean_run_superseded_but_stays_clean(self, repo, team):
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
        logic.mark_run_completed(clean_run.id)

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
