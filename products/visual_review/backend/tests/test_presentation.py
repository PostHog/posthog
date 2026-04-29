"""Integration tests for visual_review DRF views."""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.visual_review.backend import logic
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


class TestRepoViewSet(APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_create_repo(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/repos/",
            {"repo_external_id": 12345, "repo_full_name": "org/my-repo"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["repo_full_name"] == "org/my-repo"
        assert data["repo_external_id"] == 12345
        assert "id" in data

    def test_list_repos(self):
        existing_count = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/").json()["count"]
        api.create_repo(team_id=self.team.id, repo_external_id=111, repo_full_name="org/first")
        api.create_repo(team_id=self.team.id, repo_external_id=222, repo_full_name="org/second")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] - existing_count == 2

    def test_retrieve_project(self):
        repo = api.create_repo(team_id=self.team.id, repo_external_id=333, repo_full_name="org/test")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{repo.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["repo_full_name"] == "org/test"

    def test_retrieve_project_not_found(self):
        import uuid

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{uuid.uuid4()}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestRunViewSet(APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self):
        super().setUp()
        self.vr_project = api.create_repo(team_id=self.team.id, repo_external_id=99999, repo_full_name="org/test")

    @patch("products.visual_review.backend.storage.ArtifactStorage.get_presigned_upload_url")
    def test_create_run(self, mock_presigned):
        mock_presigned.return_value = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "value"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/",
            {
                "repo_id": str(self.vr_project.id),
                "run_type": "storybook",
                "commit_sha": "abc123def456789",
                "branch": "main",
                "pr_number": 42,
                "snapshots": [
                    {"identifier": "Button-primary", "content_hash": "hash1", "width": 100, "height": 200},
                    {"identifier": "Card-default", "content_hash": "hash2", "width": 150, "height": 250},
                ],
                "baseline_hashes": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "run_id" in data
        assert "uploads" in data
        assert len(data["uploads"]) == 2
        upload_hashes = {u["content_hash"] for u in data["uploads"]}
        assert upload_hashes == {"hash1", "hash2"}

    def test_retrieve_run(self):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            ),
            team_id=self.team.id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["commit_sha"] == "abc123"
        assert data["status"] == "pending"

    def test_get_run_snapshots(self):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="h1"),
                    SnapshotManifestItem(identifier="Card", content_hash="h2"),
                ],
            ),
            team_id=self.team.id,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/snapshots/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        results = data["results"]
        assert len(results) == 2
        identifiers = {s["identifier"] for s in results}
        assert identifiers == {"Button", "Card"}

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run_no_changes(self, mock_delay):
        """Runs with no changes complete immediately without triggering diff task."""
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            ),
            team_id=self.team.id,
        )

        response = self.client.post(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/complete/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "completed"
        mock_delay.assert_not_called()

    def test_approve_run(self):
        # Create artifact directly via logic (API no longer exposes register_artifact)
        logic.get_or_create_artifact(
            repo_id=self.vr_project.id,
            content_hash="new_hash",
            storage_path="visual_review/new_hash",
        )

        # Create run with changed snapshot
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            ),
            team_id=self.team.id,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/approve/",
            {
                "snapshots": [{"identifier": "Button", "new_hash": "new_hash"}],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        # Per-snapshot approval is DB only — run not finalized
        assert not response.json()["run"]["approved"]
