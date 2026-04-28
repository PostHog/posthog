import io

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from PIL import Image

from products.visual_review.backend.diff import THUMB_HEIGHT, THUMB_WIDTH, CompareResult
from products.visual_review.backend.diffing import _store_thumbnail
from products.visual_review.backend.facade.enums import RunType, SnapshotResult
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


def _make_png(width: int = 800, height: int = 600, color: tuple[int, ...] = (200, 100, 50, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_repo(team) -> Repo:
    return Repo.objects.create(
        team_id=team.id,
        repo_external_id=12345,
        repo_full_name="org/test-repo",
    )


def _make_artifact(repo: Repo, content_hash: str) -> Artifact:
    return Artifact.objects.create(
        repo=repo,
        team_id=repo.team_id,
        content_hash=content_hash,
        storage_path=f"visual_review/{content_hash}",
        width=800,
        height=600,
    )


def _make_run_with_snapshot(
    repo: Repo,
    identifier: str = "button--primary",
    current_hash: str = "abc123",
    result: str = SnapshotResult.CHANGED,
) -> tuple[Run, RunSnapshot]:
    run = Run.objects.create(
        repo=repo,
        team_id=repo.team_id,
        run_type=RunType.STORYBOOK,
        commit_sha="sha1",
        branch="main",
    )
    artifact = _make_artifact(repo, current_hash)
    snapshot = RunSnapshot.objects.create(
        run=run,
        team_id=repo.team_id,
        identifier=identifier,
        current_hash=current_hash,
        current_artifact=artifact,
        result=result,
    )
    return run, snapshot


def _make_compare_result(thumbnail: bytes = b"fake-webp") -> CompareResult:
    return CompareResult(
        diff_image=b"fake-diff",
        diff_hash="diff_hash",
        diff_percentage=5.0,
        diff_pixel_count=100,
        ssim_score=0.95,
        width=800,
        height=600,
        thumbnail=thumbnail,
        thumbnail_hash="thumb_hash_auto",
    )


@pytest.mark.django_db(databases=list(PRODUCT_DATABASES))
class TestStoreThumbnail:
    @patch("products.visual_review.backend.logic.write_artifact_bytes")
    def test_stores_thumbnail_and_links_to_artifact(self, mock_write, team):
        repo = _make_repo(team)
        _run, snapshot = _make_run_with_snapshot(repo)

        thumb_artifact = _make_artifact(repo, "thumb_hash_auto")
        mock_write.return_value = thumb_artifact

        _store_thumbnail(snapshot, _make_compare_result())

        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args
        assert call_kwargs[1]["width"] == THUMB_WIDTH
        assert call_kwargs[1]["height"] == THUMB_HEIGHT
        assert call_kwargs[1]["repo_id"] == repo.id

        artifact = snapshot.current_artifact
        assert artifact is not None
        artifact.refresh_from_db()
        assert artifact.thumbnail == thumb_artifact

    @patch("products.visual_review.backend.logic.write_artifact_bytes")
    def test_skips_when_thumbnail_already_exists(self, mock_write, team):
        repo = _make_repo(team)
        _run, snapshot = _make_run_with_snapshot(repo)

        artifact = snapshot.current_artifact
        assert artifact is not None
        existing_thumb = _make_artifact(repo, "existing_thumb")
        artifact.thumbnail = existing_thumb
        artifact.save(update_fields=["thumbnail"])

        _store_thumbnail(snapshot, _make_compare_result())

        mock_write.assert_not_called()

    @patch("products.visual_review.backend.logic.write_artifact_bytes")
    def test_skips_when_no_thumbnail_in_result(self, mock_write, team):
        repo = _make_repo(team)
        _run, snapshot = _make_run_with_snapshot(repo)

        result = _make_compare_result()
        result.thumbnail = None
        result.thumbnail_hash = ""

        _store_thumbnail(snapshot, result)

        mock_write.assert_not_called()

    def test_skips_when_no_current_artifact(self, team):
        repo = _make_repo(team)
        run = Run.objects.create(
            repo=repo,
            team_id=repo.team_id,
            run_type=RunType.STORYBOOK,
            commit_sha="sha1",
            branch="main",
        )
        snapshot = RunSnapshot.objects.create(
            run=run,
            team_id=repo.team_id,
            identifier="test",
            current_hash="",
            result=SnapshotResult.REMOVED,
        )

        _store_thumbnail(snapshot, _make_compare_result())
        # Should not raise


@pytest.mark.django_db(databases=list(PRODUCT_DATABASES))
class TestThumbnailEndpoint(APIBaseTest):
    databases = PRODUCT_DATABASES
    THUMB_HASH = "thumb_hash_abc"
    IDENTIFIER = "button--primary"

    def setUp(self):
        super().setUp()
        self.repo = Repo.objects.create(
            team_id=self.team.id,
            repo_external_id=99999,
            repo_full_name="org/test",
        )

    def _seed_snapshot_with_thumbnail(self) -> None:
        thumb_artifact = Artifact.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            content_hash=self.THUMB_HASH,
            storage_path=f"visual_review/{self.THUMB_HASH}",
        )
        current_artifact = Artifact.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            content_hash="current_hash_123",
            storage_path="visual_review/current_hash_123",
            thumbnail=thumb_artifact,
        )
        run = Run.objects.create(
            repo=self.repo,
            team_id=self.team.id,
            run_type=RunType.STORYBOOK,
            commit_sha="abc",
            branch="main",
        )
        RunSnapshot.objects.create(
            run=run,
            team_id=self.team.id,
            identifier=self.IDENTIFIER,
            current_hash="current_hash_123",
            current_artifact=current_artifact,
            result=SnapshotResult.CHANGED,
        )

    def _thumbnail_url(self, identifier: str | None = None) -> str:
        ident = identifier if identifier is not None else self.IDENTIFIER
        return f"/api/projects/{self.team.id}/visual_review/repos/{self.repo.id}/thumbnails/{ident}/"

    def test_returns_thumbnail_bytes(self):
        self._seed_snapshot_with_thumbnail()
        thumb_content = b"fake-webp-bytes"

        with patch("products.visual_review.backend.storage.ArtifactStorage.read", return_value=thumb_content):
            response = self.client.get(self._thumbnail_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response.content, thumb_content)
        self.assertIn("ETag", response)
        self.assertIn("max-age=300", response["Cache-Control"])
        # Shared caches must key per-credential — see views.thumbnail.
        self.assertIn("Authorization", response["Vary"])
        self.assertIn("Cookie", response["Vary"])

    def test_returns_304_on_etag_match(self):
        self._seed_snapshot_with_thumbnail()

        response = self.client.get(self._thumbnail_url(), HTTP_IF_NONE_MATCH=f'"{self.THUMB_HASH}"')

        self.assertEqual(response.status_code, 304)
        self.assertIn("Authorization", response["Vary"])
        self.assertIn("Cookie", response["Vary"])

    def test_returns_404_when_no_thumbnail(self):
        response = self.client.get(self._thumbnail_url("nonexistent"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_returns_404_for_unknown_repo(self):
        import uuid

        response = self.client.get(
            f"/api/projects/{self.team.id}/visual_review/repos/{uuid.uuid4()}/thumbnails/{self.IDENTIFIER}/"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Cache-Control"], "no-store")
