"""Tests for visual_review models."""

import uuid

import pytest

from products.visual_review.backend.facade.enums import RunStatus, SnapshotResult
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestProject:
    def test_str_returns_name(self, team):
        repo = Repo.objects.create(team_id=team.id, repo_external_id=111, repo_full_name="org/my-repo")
        assert str(repo) == "org/my-repo"

    def test_id_is_uuid(self, team):
        repo = Repo.objects.create(team_id=team.id, repo_external_id=222, repo_full_name="org/test")
        assert isinstance(repo.id, uuid.UUID)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestArtifact:
    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=222, repo_full_name="org/test")

    def test_str_shows_truncated_hash(self, repo):
        artifact = Artifact.objects.create(
            repo=repo, team_id=repo.team_id, content_hash="abcdef123456789", storage_path="visual_review/abc"
        )
        assert str(artifact) == "abcdef123456..."

    def test_unique_hash_per_project(self, repo):
        Artifact.objects.create(repo=repo, team_id=repo.team_id, content_hash="hash123", storage_path="p/hash123")

        with pytest.raises(Exception):  # IntegrityError
            Artifact.objects.create(
                repo=repo, team_id=repo.team_id, content_hash="hash123", storage_path="p/hash123-dup"
            )


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRun:
    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=222, repo_full_name="org/test")

    def test_str_shows_id_and_status(self, repo):
        run = Run.objects.create(repo=repo, team_id=repo.team_id, commit_sha="abc123", branch="main")
        assert "pending" in str(run).lower()

    def test_default_status_is_pending(self, repo):
        run = Run.objects.create(repo=repo, team_id=repo.team_id, commit_sha="abc123", branch="main")
        assert run.status == RunStatus.PENDING

    def test_ordering_by_created_at_desc(self, repo):
        run1 = Run.objects.create(
            repo=repo, team_id=repo.team_id, commit_sha="first", branch="main", run_type="storybook"
        )
        run2 = Run.objects.create(
            repo=repo, team_id=repo.team_id, commit_sha="second", branch="main", run_type="playwright"
        )

        runs = list(Run.objects.filter(repo=repo))
        assert runs[0].id == run2.id  # Most recent first
        assert runs[1].id == run1.id


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestRunSnapshot:
    @pytest.fixture
    def repo(self, team):
        return Repo.objects.create(team_id=team.id, repo_external_id=222, repo_full_name="org/test")

    @pytest.fixture
    def run(self, repo):
        return Run.objects.create(repo=repo, team_id=repo.team_id, commit_sha="abc123", branch="main")

    def test_str_shows_identifier_and_result(self, run):
        snapshot = RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier="Button-primary")
        assert "Button-primary" in str(snapshot)
        assert "unchanged" in str(snapshot).lower()

    def test_default_result_is_unchanged(self, run):
        snapshot = RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier="Test")
        assert snapshot.result == SnapshotResult.UNCHANGED

    def test_unique_identifier_per_run(self, run):
        RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier="Button")

        with pytest.raises(Exception):  # IntegrityError
            RunSnapshot.objects.create(run=run, team_id=run.team_id, identifier="Button")
