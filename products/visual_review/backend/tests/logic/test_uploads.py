"""Unit tests for logic/uploads.py — Upload verification and artifact creation."""

import pytest

from django.db import connections
from django.test.utils import CaptureQueriesContext

from products.visual_review.backend.db import WRITER_DB
from products.visual_review.backend.facade.contracts import CreateRunInput, SnapshotManifestItem
from products.visual_review.backend.facade.enums import RunType
from products.visual_review.backend.logic import artifact_store, errors, repos, runs, uploads
from products.visual_review.backend.models import Run, RunSnapshot
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
class TestVerifyUploadsAndCreateArtifacts:
    """Server-side hash integrity for uploaded PNGs."""

    @pytest.fixture
    def repo(self, team):
        return repos.create_repo(team_id=team.id, repo_external_id=42424, repo_full_name="org/vr")

    def _png(self, color: tuple[int, int, int, int]) -> bytes:
        import io as _io

        from PIL import Image as _Image

        img = _Image.new("RGBA", (8, 8), color)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_creates_artifact_with_server_computed_hash(self, repo, mocker):
        from products.visual_review.backend.hashing import hash_image

        png = self._png((10, 20, 30, 255))
        server_hash = hash_image(png)

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="sha",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Card", content_hash=server_hash)],
            ),
            team_id=repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            return_value=png,
        )

        created = uploads.verify_uploads_and_create_artifacts(run.id)

        assert created == 1
        artifact = artifact_store.get_artifact(repo.id, server_hash)
        assert artifact is not None
        assert artifact.content_hash == server_hash
        assert artifact.size_bytes == len(png)
        snapshot = RunSnapshot.objects.get(run=run)
        assert snapshot.current_artifact_id == artifact.id

    def test_verification_query_count_does_not_grow_per_hash(self, repo, mocker):
        from products.visual_review.backend.hashing import hash_image

        def create_run_with_images(count: int, color_offset: int) -> tuple[Run, dict[str, bytes]]:
            images: dict[str, bytes] = {}
            snapshots: list[SnapshotManifestItem] = []
            for index in range(count):
                png = self._png((color_offset + index, 20, 30, 255))
                content_hash = hash_image(png)
                images[content_hash] = png
                snapshots.append(
                    SnapshotManifestItem(identifier=f"Card-{color_offset}-{index}", content_hash=content_hash)
                )

            run, _ = runs.create_run(
                CreateRunInput(
                    repo_id=repo.id,
                    run_type=RunType.STORYBOOK,
                    commit_sha=f"sha-{count}-{color_offset}",
                    branch="main",
                    pr_number=None,
                    snapshots=snapshots,
                ),
                team_id=repo.team_id,
            )
            return run, images

        single_run, single_images = create_run_with_images(1, 10)
        mock_read = mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            side_effect=lambda content_hash: single_images.get(content_hash),
        )
        with CaptureQueriesContext(connections[WRITER_DB]) as single_queries:
            uploads.verify_uploads_and_create_artifacts(single_run.id)

        scaled_run, scaled_images = create_run_with_images(5, 100)
        mock_read.side_effect = lambda content_hash: scaled_images.get(content_hash)
        with CaptureQueriesContext(connections[WRITER_DB]) as scaled_queries:
            uploads.verify_uploads_and_create_artifacts(scaled_run.id)

        assert len(scaled_queries) <= len(single_queries)

    def test_verification_relinks_existing_artifacts_across_hash_batches(self, repo, mocker):
        from products.visual_review.backend.hashing import hash_image

        mocker.patch.object(artifact_store, "ARTIFACT_HASH_BATCH_SIZE", 2)
        snapshots: list[SnapshotManifestItem] = []
        for index, color in enumerate([(10, 20, 30, 255), (40, 50, 60, 255), (70, 80, 90, 255)]):
            content_hash = hash_image(self._png(color))
            artifact_store.get_or_create_artifact(repo.id, content_hash, f"visual_review/{content_hash}")
            snapshots.append(SnapshotManifestItem(identifier=f"Card-{index}", content_hash=content_hash))

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="sha-retry",
                branch="main",
                pr_number=None,
                snapshots=snapshots,
            ),
            team_id=repo.team_id,
        )

        assert uploads.verify_uploads_and_create_artifacts(run.id) == 0
        assert RunSnapshot.objects.filter(run=run, current_artifact__isnull=False).count() == 3

    def test_hash_mismatch_raises_and_persists_no_artifacts(self, repo, mocker):
        # Two snapshots: first verifies cleanly, second has a mismatched claim.
        # The two-pass split must prevent the first artifact from being written
        # before the second is checked.
        from products.visual_review.backend.hashing import hash_image

        png_a = self._png((255, 0, 0, 255))
        png_b = self._png((0, 0, 255, 255))
        good_hash = hash_image(png_a)
        bad_claim = "f" * 64  # nothing hashes to this

        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="sha",
                branch="main",
                pr_number=None,
                snapshots=[
                    SnapshotManifestItem(identifier="Good", content_hash=good_hash),
                    SnapshotManifestItem(identifier="Bad", content_hash=bad_claim),
                ],
            ),
            team_id=repo.team_id,
        )

        def _read(self, content_hash):
            return {good_hash: png_a, bad_claim: png_b}.get(content_hash)

        mocker.patch("products.visual_review.backend.storage.ArtifactStorage.read", autospec=True, side_effect=_read)

        with pytest.raises(errors.HashIntegrityError):
            uploads.verify_uploads_and_create_artifacts(run.id)

        assert artifact_store.get_artifact(repo.id, good_hash) is None
        assert artifact_store.get_artifact(repo.id, bad_claim) is None

    def test_corrupt_png_raises_hash_integrity_error(self, repo, mocker):
        run, _ = runs.create_run(
            CreateRunInput(
                repo_id=repo.id,
                run_type=RunType.STORYBOOK,
                commit_sha="sha",
                branch="main",
                pr_number=None,
                snapshots=[SnapshotManifestItem(identifier="Card", content_hash="a" * 64)],
            ),
            team_id=repo.team_id,
        )

        mocker.patch(
            "products.visual_review.backend.storage.ArtifactStorage.read",
            return_value=b"not a png",
        )

        with pytest.raises(errors.HashIntegrityError):
            uploads.verify_uploads_and_create_artifacts(run.id)
