"""Tests for visual_review models."""

import uuid

import pytest

from products.visual_review.backend.domain_types import RunStatus, SnapshotResult
from products.visual_review.backend.models import Artifact, Project, Run, RunSnapshot


@pytest.mark.django_db
class TestProject:
    def test_str_returns_name(self, team):
        project = Project.objects.create(team=team, name="My Project")
        assert str(project) == "My Project"

    def test_id_is_uuid(self, team):
        project = Project.objects.create(team=team, name="Test")
        assert isinstance(project.id, uuid.UUID)


@pytest.mark.django_db
class TestArtifact:
    @pytest.fixture
    def project(self, team):
        return Project.objects.create(team=team, name="Test")

    def test_str_shows_truncated_hash(self, project):
        artifact = Artifact.objects.create(
            project=project, content_hash="abcdef123456789", storage_path="visual_review/abc"
        )
        assert str(artifact) == "abcdef123456..."

    def test_unique_hash_per_project(self, project):
        Artifact.objects.create(project=project, content_hash="hash123", storage_path="p/hash123")

        with pytest.raises(Exception):  # IntegrityError
            Artifact.objects.create(project=project, content_hash="hash123", storage_path="p/hash123-dup")


@pytest.mark.django_db
class TestRun:
    @pytest.fixture
    def project(self, team):
        return Project.objects.create(team=team, name="Test")

    def test_str_shows_id_and_status(self, project):
        run = Run.objects.create(project=project, commit_sha="abc123", branch="main")
        assert "pending" in str(run).lower()

    def test_default_status_is_pending(self, project):
        run = Run.objects.create(project=project, commit_sha="abc123", branch="main")
        assert run.status == RunStatus.PENDING

    def test_ordering_by_created_at_desc(self, project):
        run1 = Run.objects.create(project=project, commit_sha="first", branch="main")
        run2 = Run.objects.create(project=project, commit_sha="second", branch="main")

        runs = list(Run.objects.filter(project=project))
        assert runs[0].id == run2.id  # Most recent first
        assert runs[1].id == run1.id


@pytest.mark.django_db
class TestRunSnapshot:
    @pytest.fixture
    def project(self, team):
        return Project.objects.create(team=team, name="Test")

    @pytest.fixture
    def run(self, project):
        return Run.objects.create(project=project, commit_sha="abc123", branch="main")

    def test_str_shows_identifier_and_result(self, run):
        snapshot = RunSnapshot.objects.create(run=run, identifier="Button-primary")
        assert "Button-primary" in str(snapshot)
        assert "unchanged" in str(snapshot).lower()

    def test_default_result_is_unchanged(self, run):
        snapshot = RunSnapshot.objects.create(run=run, identifier="Test")
        assert snapshot.result == SnapshotResult.UNCHANGED

    def test_unique_identifier_per_run(self, run):
        RunSnapshot.objects.create(run=run, identifier="Button")

        with pytest.raises(Exception):  # IntegrityError
            RunSnapshot.objects.create(run=run, identifier="Button")
