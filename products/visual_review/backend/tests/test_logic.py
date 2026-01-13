"""Unit tests for visual_review business logic."""

import pytest

from products.visual_review.backend import logic
from products.visual_review.backend.domain_types import RunStatus, RunType, SnapshotResult


@pytest.mark.django_db
class TestProjectOperations:
    def test_create_project(self, team):
        project = logic.create_project(team_id=team.id, name="My Project")

        assert project.team_id == team.id
        assert project.name == "My Project"

    def test_get_project(self, team):
        project = logic.create_project(team_id=team.id, name="Test")

        retrieved = logic.get_project(project.id)

        assert retrieved.id == project.id
        assert retrieved.name == "Test"

    def test_get_project_not_found(self):
        import uuid

        with pytest.raises(logic.ProjectNotFoundError):
            logic.get_project(uuid.uuid4())

    def test_list_projects_for_team(self, team):
        logic.create_project(team_id=team.id, name="First")
        logic.create_project(team_id=team.id, name="Second")

        projects = logic.list_projects_for_team(team.id)

        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"First", "Second"}


@pytest.mark.django_db
class TestArtifactOperations:
    @pytest.fixture
    def project(self, team):
        return logic.create_project(team_id=team.id, name="Test")

    def test_get_or_create_artifact_creates_new(self, project):
        artifact, created = logic.get_or_create_artifact(
            project_id=project.id,
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

    def test_get_or_create_artifact_returns_existing(self, project):
        artifact1, created1 = logic.get_or_create_artifact(
            project_id=project.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )
        artifact2, created2 = logic.get_or_create_artifact(
            project_id=project.id,
            content_hash="abc123",
            storage_path="visual_review/abc123",
        )

        assert created1 is True
        assert created2 is False
        assert artifact1.id == artifact2.id

    def test_get_artifact(self, project):
        logic.get_or_create_artifact(
            project_id=project.id,
            content_hash="xyz789",
            storage_path="visual_review/xyz789",
        )

        artifact = logic.get_artifact(project.id, "xyz789")

        assert artifact is not None
        assert artifact.content_hash == "xyz789"

    def test_get_artifact_not_found(self, project):
        artifact = logic.get_artifact(project.id, "nonexistent")

        assert artifact is None

    def test_find_missing_hashes(self, project):
        logic.get_or_create_artifact(project_id=project.id, content_hash="exists1", storage_path="p/exists1")
        logic.get_or_create_artifact(project_id=project.id, content_hash="exists2", storage_path="p/exists2")

        missing = logic.find_missing_hashes(project.id, ["exists1", "missing1", "exists2", "missing2"])

        assert set(missing) == {"missing1", "missing2"}

    def test_find_missing_hashes_all_exist(self, project):
        logic.get_or_create_artifact(project_id=project.id, content_hash="a", storage_path="p/a")
        logic.get_or_create_artifact(project_id=project.id, content_hash="b", storage_path="p/b")

        missing = logic.find_missing_hashes(project.id, ["a", "b"])

        assert missing == []


@pytest.mark.django_db
class TestRunOperations:
    @pytest.fixture
    def project(self, team):
        return logic.create_project(team_id=team.id, name="Test")

    def test_create_run_basic(self, project):
        run, missing = logic.create_run(
            project_id=project.id,
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

        assert run.project_id == project.id
        assert run.run_type == RunType.STORYBOOK
        assert run.commit_sha == "abc123def456"
        assert run.branch == "main"
        assert run.pr_number == 42
        assert run.status == RunStatus.PENDING
        assert run.total_snapshots == 2
        assert set(missing) == {"hash1", "hash2"}

    def test_create_run_with_existing_artifacts(self, project):
        logic.get_or_create_artifact(project_id=project.id, content_hash="existing", storage_path="p/existing")

        run, missing = logic.create_run(
            project_id=project.id,
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

        assert missing == ["new"]

    def test_create_run_with_baselines(self, project):
        baseline_artifact, _ = logic.get_or_create_artifact(
            project_id=project.id, content_hash="baseline_hash", storage_path="p/baseline"
        )

        run, missing = logic.create_run(
            project_id=project.id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[{"identifier": "Button", "content_hash": "new_hash"}],
            baseline_hashes={"Button": "baseline_hash"},
        )

        snapshot = run.snapshots.first()
        assert snapshot.baseline_artifact_id == baseline_artifact.id
        assert snapshot.result == SnapshotResult.CHANGED

    def test_create_run_snapshot_results(self, project):
        baseline_artifact, _ = logic.get_or_create_artifact(
            project_id=project.id, content_hash="same_hash", storage_path="p/same"
        )

        run, _ = logic.create_run(
            project_id=project.id,
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

    def test_get_run(self, project):
        run, _ = logic.create_run(
            project_id=project.id,
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

    def test_mark_run_processing(self, project):
        run, _ = logic.create_run(
            project_id=project.id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
            pr_number=None,
            snapshots=[],
            baseline_hashes={},
        )

        updated = logic.mark_run_processing(run.id)

        assert updated.status == RunStatus.PROCESSING

    def test_mark_run_completed_success(self, project):
        run, _ = logic.create_run(
            project_id=project.id,
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

    def test_mark_run_completed_with_error(self, project):
        run, _ = logic.create_run(
            project_id=project.id,
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
    def project(self, team):
        return logic.create_project(team_id=team.id, name="Test")

    def test_approve_run(self, project, user):
        current_artifact, _ = logic.get_or_create_artifact(
            project_id=project.id, content_hash="new_hash", storage_path="p/new"
        )
        run, _ = logic.create_run(
            project_id=project.id,
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

        snapshot = updated.snapshots.first()
        assert snapshot.baseline_artifact_id == current_artifact.id
        assert snapshot.result == SnapshotResult.UNCHANGED


@pytest.mark.django_db
class TestGetRunSnapshots:
    @pytest.fixture
    def project(self, team):
        return logic.create_project(team_id=team.id, name="Test")

    def test_get_run_snapshots(self, project):
        run, _ = logic.create_run(
            project_id=project.id,
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
