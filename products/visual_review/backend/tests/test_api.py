"""Unit tests for visual_review facade API."""

from uuid import UUID

import pytest
from unittest.mock import patch

from products.visual_review.backend.api import api
from products.visual_review.backend.api.dtos import (
    ApproveRunInput,
    ApproveSnapshotInput,
    CreateRunInput,
    RegisterArtifactInput,
    SnapshotManifestItem,
)
from products.visual_review.backend.domain_types import RunType, SnapshotResult


@pytest.mark.django_db
class TestProjectAPI:
    def test_create_project_returns_dto(self, team):
        result = api.create_project(team_id=team.id, name="My Project")

        assert isinstance(result.id, UUID)
        assert result.team_id == team.id
        assert result.name == "My Project"

    def test_get_project_returns_dto(self, team):
        created = api.create_project(team_id=team.id, name="Test")

        result = api.get_project(created.id)

        assert result.id == created.id
        assert result.name == "Test"

    def test_get_project_not_found_raises(self):
        import uuid

        with pytest.raises(api.ProjectNotFoundError):
            api.get_project(uuid.uuid4())

    def test_list_projects_returns_dtos(self, team):
        api.create_project(team_id=team.id, name="First")
        api.create_project(team_id=team.id, name="Second")

        result = api.list_projects(team.id)

        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"First", "Second"}


@pytest.mark.django_db
class TestArtifactAPI:
    @pytest.fixture
    def project(self, team):
        return api.create_project(team_id=team.id, name="Test")

    def test_register_artifact_returns_dto(self, project):
        result = api.register_artifact(
            RegisterArtifactInput(
                project_id=project.id,
                content_hash="abc123",
                storage_path="visual_review/abc123",
                width=100,
                height=200,
                size_bytes=5000,
            )
        )

        assert isinstance(result.id, UUID)
        assert result.content_hash == "abc123"
        assert result.width == 100
        assert result.height == 200

    @patch("products.visual_review.backend.logic.get_presigned_upload_url")
    def test_get_upload_url(self, mock_presigned, project):
        mock_presigned.return_value = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "value"},
        }

        result = api.get_upload_url(project.id, "somehash")

        assert result is not None
        assert result.url == "https://s3.example.com/upload"
        assert result.fields == {"key": "value"}

    @patch("products.visual_review.backend.logic.get_presigned_upload_url")
    def test_get_upload_url_storage_disabled(self, mock_presigned, project):
        mock_presigned.return_value = None

        result = api.get_upload_url(project.id, "somehash")

        assert result is None


@pytest.mark.django_db
class TestRunAPI:
    @pytest.fixture
    def project(self, team):
        return api.create_project(team_id=team.id, name="Test")

    def test_create_run_returns_result(self, project):
        result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="hash1"),
                    SnapshotManifestItem(identifier="Card", content_hash="hash2"),
                ],
            )
        )

        assert isinstance(result.run_id, UUID)
        assert set(result.missing_hashes) == {"hash1", "hash2"}

    def test_get_run_returns_dto(self, project):
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        result = api.get_run(create_result.run_id)

        assert result.id == create_result.run_id
        assert result.commit_sha == "abc123"
        assert result.summary.total == 0

    def test_get_run_snapshots_returns_dtos(self, project):
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="hash1"),
                    SnapshotManifestItem(identifier="Card", content_hash="hash2"),
                ],
            )
        )

        snapshots = api.get_run_snapshots(create_result.run_id)

        assert len(snapshots) == 2
        assert all(isinstance(s.id, UUID) for s in snapshots)
        identifiers = {s.identifier for s in snapshots}
        assert identifiers == {"Button", "Card"}

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run_triggers_task(self, mock_delay, project):
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        result = api.complete_run(create_result.run_id)

        assert result.status == "processing"
        mock_delay.assert_called_once_with(str(create_result.run_id))


@pytest.mark.django_db
class TestApproveRunAPI:
    @pytest.fixture
    def project(self, team):
        return api.create_project(team_id=team.id, name="Test")

    def test_approve_run(self, project, user):
        # Create artifact first
        api.register_artifact(
            RegisterArtifactInput(
                project_id=project.id,
                content_hash="new_hash",
                storage_path="visual_review/new_hash",
            )
        )

        # Create run with a changed snapshot
        create_result = api.create_run(
            CreateRunInput(
                project_id=project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            )
        )

        result = api.approve_run(
            ApproveRunInput(
                run_id=create_result.run_id,
                user_id=user.id,
                snapshots=[ApproveSnapshotInput(identifier="Button", new_hash="new_hash")],
            )
        )

        assert result.approved is True
        assert result.approved_at is not None

        # Check snapshot was updated
        snapshots = api.get_run_snapshots(create_result.run_id)
        button_snap = next(s for s in snapshots if s.identifier == "Button")
        assert button_snap.result == SnapshotResult.UNCHANGED
