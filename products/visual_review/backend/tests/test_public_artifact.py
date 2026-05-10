"""Tests for the unauthenticated public artifact redirect endpoint."""

from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import Client

from products.visual_review.backend.models import Artifact, Repo
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES, VisualReviewTeamScopedTestMixin


class TestPublicArtifactView(VisualReviewTeamScopedTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.repo = Repo.objects.create(
            team_id=self.team.id,
            repo_external_id=12321,
            repo_full_name="org/public-artifact-test",
        )
        self.artifact = Artifact.objects.create(
            team_id=self.team.id,
            repo=self.repo,
            content_hash="abcdef1234",
            storage_path="visual_review/foo/abcdef1234",
        )

    def test_redirects_to_presigned_url(self) -> None:
        client = Client()  # unauthenticated

        with patch(
            "products.visual_review.backend.presentation.public_views.ArtifactStorage.get_presigned_download_url",
            return_value="https://s3.example.com/bucket/key?signature=xyz",
        ) as mock_get:
            response = client.get(f"/api/visual_review/public/artifact/{self.artifact.id}")

        assert response.status_code == 302
        assert response["Location"] == "https://s3.example.com/bucket/key?signature=xyz"
        cache_control = response.get("Cache-Control", "")
        assert "max-age=86400" in cache_control
        assert "immutable" in cache_control
        mock_get.assert_called_once_with("abcdef1234", expiration=3600)

    def test_unknown_artifact_returns_404(self) -> None:
        client = Client()
        response = client.get(f"/api/visual_review/public/artifact/{uuid4()}")
        assert response.status_code == 404

    def test_storage_disabled_returns_404(self) -> None:
        client = Client()
        with patch(
            "products.visual_review.backend.presentation.public_views.ArtifactStorage.get_presigned_download_url",
            return_value=None,
        ):
            response = client.get(f"/api/visual_review/public/artifact/{self.artifact.id}")
        assert response.status_code == 404

    def test_post_method_not_allowed(self) -> None:
        client = Client()
        response = client.post(f"/api/visual_review/public/artifact/{self.artifact.id}")
        assert response.status_code == 405
