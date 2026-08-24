"""Upload verification: server-side hashing of uploaded PNGs before they become artifacts."""

from __future__ import annotations

from uuid import UUID

import structlog

from ..models import Artifact
from ..storage import ArtifactStorage
from . import artifact_store, errors, run_queries

logger = structlog.get_logger(__name__)


def verify_uploads_and_create_artifacts(run_id: UUID) -> int:
    """
    Verify S3 uploads, check hash integrity, and create Artifact records.

    For each new upload (no existing Artifact), reads the PNG bytes from S3,
    decodes to sRGB RGBA, and computes the BLAKE3 hash. The CLI-claimed hash
    is used only as a lookup key into S3 — once verified, it's discarded and
    the server-computed hash is used everywhere downstream. This ensures the
    CLI cannot (accidentally or maliciously) associate wrong hashes with image
    content.

    Verification runs in two passes so a late failure can't leave a partial
    set of Artifact rows behind: pass 1 reads + hashes all uploads, pass 2
    creates Artifact rows from the verified results.

    Raises HashIntegrityError if any upload fails verification.

    Returns number of artifacts created.
    """
    from ..hashing import ImageTooLargeError, hash_image

    run = run_queries.get_run(run_id)
    repo_id = run.repo_id
    storage = ArtifactStorage(str(repo_id))

    # Collect all unique hashes we expect, keyed by the CLI-claimed value.
    # The claim is treated as a lookup key only — verification below produces
    # the server-computed hash that becomes authoritative.
    expected_hashes: dict[str, dict[str, int | None]] = {}
    snapshots = run.snapshots.values_list("current_hash", "current_width", "current_height", "baseline_hash")
    for current_hash, current_width, current_height, baseline_hash in snapshots.iterator(chunk_size=1000):
        if current_hash and current_hash not in expected_hashes:
            expected_hashes[current_hash] = {
                "width": current_width,
                "height": current_height,
            }
        if baseline_hash and baseline_hash not in expected_hashes:
            expected_hashes[baseline_hash] = {
                "width": None,
                "height": None,
            }

    existing_hashes: set[str] = set()
    for hash_batch in artifact_store._iter_batches(expected_hashes, artifact_store.ARTIFACT_HASH_BATCH_SIZE):
        existing_hashes.update(
            Artifact.objects.filter(repo_id=repo_id, content_hash__in=hash_batch).values_list("content_hash", flat=True)
        )

    # Pass 1: read + hash all new uploads. Skip existing artifacts. Fail loudly
    # on any hash mismatch, decode error, or missing upload before any Artifact
    # row is written.
    verified: list[tuple[str, int, dict[str, int | None]]] = []
    for claimed_hash, metadata in expected_hashes.items():
        if claimed_hash in existing_hashes:
            continue

        png_bytes = storage.read(claimed_hash)
        if png_bytes is None:
            # Race: complete_run fired before the CLI's S3 upload landed, or
            # the upload was never made. Log loudly so we can spot it instead
            # of silently dropping the artifact and forcing the next run to
            # re-upload the same content.
            logger.warning(
                "visual_review.upload_missing_in_s3",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
            )
            continue
        if len(png_bytes) == 0:
            raise errors.HashIntegrityError(f"Upload rejected: empty file for hash {claimed_hash[:16]}…")

        try:
            actual_hash = hash_image(png_bytes)
        except ImageTooLargeError as e:
            logger.exception(
                "visual_review.hash_image_too_large",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                error=str(e),
            )
            raise errors.HashIntegrityError(f"Upload rejected: {e}") from e
        except Exception as e:
            # Pillow can raise UnidentifiedImageError, DecompressionBombError,
            # OSError, etc. Funnel everything into HashIntegrityError so the
            # task handler routes it through the structured-failure path
            # instead of celery's retry loop.
            logger.exception(
                "visual_review.hash_image_failed",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise errors.HashIntegrityError(
                f"Upload integrity check failed: could not decode image for hash {claimed_hash[:16]}…"
            ) from e

        if actual_hash != claimed_hash:
            logger.error(
                "visual_review.hash_integrity_failure",
                run_id=str(run_id),
                claimed_hash=claimed_hash,
                actual_hash=actual_hash,
            )
            raise errors.HashIntegrityError(
                f"Upload integrity check failed: claimed {claimed_hash[:16]}… but image hashes to {actual_hash[:16]}…"
            )

        verified.append((actual_hash, len(png_bytes), metadata))

    # Pass 2: create Artifact rows from verified server-computed hashes only.
    # The claimed hash isn't used past this point.
    artifacts = [
        Artifact(
            repo_id=repo_id,
            content_hash=actual_hash,
            storage_path=storage._key(actual_hash),
            width=metadata.get("width"),
            height=metadata.get("height"),
            size_bytes=size_bytes,
            team_id=run.team_id,
        )
        for actual_hash, size_bytes, metadata in verified
    ]
    Artifact.objects.bulk_create(artifacts, batch_size=artifact_store.ARTIFACT_HASH_BATCH_SIZE, ignore_conflicts=True)
    artifact_store.link_artifacts_to_snapshots(repo_id, set(expected_hashes), run_id=run_id)

    return len(artifacts)
