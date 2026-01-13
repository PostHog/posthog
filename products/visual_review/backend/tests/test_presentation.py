"""Integration tests for visual_review DRF views."""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.visual_review.backend.api import api
from products.visual_review.backend.api.dtos import CreateRunInput, RegisterArtifactInput, SnapshotManifestItem
from products.visual_review.backend.domain_types import RunType


class TestProjectViewSet(APIBaseTest):
    def test_create_project(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/projects/",
            {"name": "My Project"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "My Project")
        self.assertIn("id", data)

    def test_list_projects(self):
        api.create_project(team_id=self.team.id, name="First")
        api.create_project(team_id=self.team.id, name="Second")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/projects/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_retrieve_project(self):
        project = api.create_project(team_id=self.team.id, name="Test")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/projects/{project.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test")

    def test_retrieve_project_not_found(self):
        import uuid

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/projects/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.visual_review.backend.logic.get_presigned_upload_url")
    def test_get_upload_url(self, mock_presigned):
        mock_presigned.return_value = {
            "url": "https://s3.example.com/upload",
            "fields": {"key": "value", "policy": "base64..."},
        }
        project = api.create_project(team_id=self.team.id, name="Test")

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/projects/{project.id}/upload-url/",
            {"content_hash": "abc123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["url"], "https://s3.example.com/upload")
        self.assertIn("fields", data)

    def test_register_artifact(self):
        project = api.create_project(team_id=self.team.id, name="Test")

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/projects/{project.id}/artifacts/",
            {
                "content_hash": "abc123def456",
                "width": 800,
                "height": 600,
                "size_bytes": 12345,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["content_hash"], "abc123def456")
        self.assertIn("id", data)


class TestRunViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.project = api.create_project(team_id=self.team.id, name="Test")

    def test_create_run(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/",
            {
                "project_id": str(self.project.id),
                "run_type": "storybook",
                "commit_sha": "abc123def456789",
                "branch": "main",
                "pr_number": 42,
                "snapshots": [
                    {"identifier": "Button-primary", "content_hash": "hash1"},
                    {"identifier": "Card-default", "content_hash": "hash2"},
                ],
                "baseline_hashes": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("run_id", data)
        self.assertEqual(set(data["missing_hashes"]), {"hash1", "hash2"})

    def test_retrieve_run(self):
        create_result = api.create_run(
            CreateRunInput(
                project_id=self.project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["commit_sha"], "abc123")
        self.assertEqual(data["status"], "pending")

    def test_get_run_snapshots(self):
        create_result = api.create_run(
            CreateRunInput(
                project_id=self.project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[
                    SnapshotManifestItem(identifier="Button", content_hash="h1"),
                    SnapshotManifestItem(identifier="Card", content_hash="h2"),
                ],
            )
        )

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/snapshots/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 2)
        identifiers = {s["identifier"] for s in data}
        self.assertEqual(identifiers, {"Button", "Card"})

    @patch("products.visual_review.backend.tasks.tasks.process_run_diffs.delay")
    def test_complete_run(self, mock_delay):
        create_result = api.create_run(
            CreateRunInput(
                project_id=self.project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[],
            )
        )

        response = self.client.post(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/complete/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "processing")
        mock_delay.assert_called_once()

    def test_approve_run(self):
        # Register artifact
        api.register_artifact(
            RegisterArtifactInput(
                project_id=self.project.id,
                content_hash="new_hash",
                storage_path="visual_review/new_hash",
            )
        )

        # Create run with changed snapshot
        create_result = api.create_run(
            CreateRunInput(
                project_id=self.project.id,
                run_type=RunType.STORYBOOK,
                commit_sha="abc123",
                branch="main",
                snapshots=[SnapshotManifestItem(identifier="Button", content_hash="new_hash")],
                baseline_hashes={"Button": "old_hash"},
            )
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/approve/",
            {
                "snapshots": [{"identifier": "Button", "new_hash": "new_hash"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["approved"])
