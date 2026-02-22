"""Integration tests for visual_review DRF views."""

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.visual_review.backend import logic
from products.visual_review.backend.facade import api
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType


class TestRepoViewSet(APIBaseTest):
    def test_create_repo(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/visual_review/repos/",
            {"name": "My Repo"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "My Repo")
        self.assertIn("id", data)

    def test_list_repos(self):
        api.create_repo(team_id=self.team.id, name="First")
        api.create_repo(team_id=self.team.id, name="Second")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_retrieve_project(self):
        repo = api.create_repo(team_id=self.team.id, name="Test")

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{repo.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Test")

    def test_retrieve_project_not_found(self):
        import uuid

        response = self.client.get(f"/api/projects/{self.team.id}/visual_review/repos/{uuid.uuid4()}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestRunViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.vr_project = api.create_repo(team_id=self.team.id, name="Test")

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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertIn("run_id", data)
        self.assertIn("uploads", data)
        self.assertEqual(len(data["uploads"]), 2)
        upload_hashes = {u["content_hash"] for u in data["uploads"]}
        self.assertEqual(upload_hashes, {"hash1", "hash2"})

    def test_retrieve_run(self):
        create_result = api.create_run(
            CreateRunInput(
                repo_id=self.vr_project.id,
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
                repo_id=self.vr_project.id,
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
        results = data["results"]
        self.assertEqual(len(results), 2)
        identifiers = {s["identifier"] for s in results}
        self.assertEqual(identifiers, {"Button", "Card"})

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
            )
        )

        response = self.client.post(f"/api/projects/{self.team.id}/visual_review/runs/{create_result.run_id}/complete/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "completed")
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
