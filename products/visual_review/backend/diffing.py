"""
Diff processing and classification for visual review.

Uses pixelhog.compare() for single-pass pixelmatch + SSIM + thumbnail.
Classifies snapshots as genuinely changed or rendering noise.

Called by the Celery task; all business logic lives here.
"""

from uuid import UUID

import structlog
from blake3 import blake3
from pixelhog import thumbnail as pixelhog_thumbnail

from .diff import THUMB_HEIGHT, THUMB_WIDTH, CompareResult, compare_images
from .diff_metadata import DiffMetadata
from .facade.enums import ChangeKind, ClassificationReason, SnapshotResult, ToleratedReason
from .models import RunSnapshot, ToleratedHash

logger = structlog.get_logger(__name__)

# Two-tier classification thresholds:
#
# 1. Pixel diff ratio — fast path for obvious changes. Snapshots above
#    this are immediately classified as CHANGED.
# 2. SSIM perceptual threshold — safety net for tall-page dilution. A real UI
#    change at the bottom of a long screenshot affects few pixels but produces
#    a measurable structural shift that SSIM catches.
#
# Only when both are below threshold is the snapshot reclassified as UNCHANGED.
PIXEL_DIFF_THRESHOLD_PERCENT = 2.5
SSIM_DISSIMILARITY_THRESHOLD = 0.01  # 1% structural difference


def classify_compare_result(result: CompareResult) -> ChangeKind | None:
    """Classify a compare result into a ChangeKind, or None for unchanged.

    Pure function — no DB, no side effects — so tests can drive every
    classification path without spinning up a snapshot row. The same logic
    drives `_diff_snapshot` below; keeping it here means the production
    branch and the tests can't drift.

    Size mismatch is *not* a kind — pixelhog pads to the largest dims and
    we still get a real pixel/SSIM answer over that padded image. The fact
    that sizes differed is recorded separately on `DiffMetadata`.
    """
    if result.diff_percentage >= PIXEL_DIFF_THRESHOLD_PERCENT:
        return ChangeKind.PIXEL
    if (1.0 - result.ssim_score) >= SSIM_DISSIMILARITY_THRESHOLD:
        return ChangeKind.STRUCTURAL
    return None


def _store_thumbnail(snapshot: RunSnapshot, result: CompareResult) -> None:
    """Store the thumbnail artifact and link it to the current artifact."""
    from . import logic

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail_id is not None:
        return
    if not result.thumbnail:
        return

    thumb_artifact = logic.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=result.thumbnail_hash,
        content=result.thumbnail,
        width=THUMB_WIDTH,
        height=THUMB_HEIGHT,
        team_id=snapshot.team_id,
    )

    artifact.thumbnail = thumb_artifact
    artifact.save(update_fields=["thumbnail"])


def _store_diff(
    snapshot: RunSnapshot,
    result: CompareResult,
    change_kind: ChangeKind,
) -> None:
    """Upload diff artifact and update snapshot metrics + classification."""
    from . import logic

    if not result.diff_image:
        return

    diff_artifact = logic.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=result.diff_hash,
        content=result.diff_image,
        width=result.width,
        height=result.height,
        team_id=snapshot.team_id,
    )

    diff_metadata = DiffMetadata(
        cluster_summary=result.cluster_summary,
        size_mismatch=result.size_mismatch,
    )

    logic.update_snapshot_diff(
        snapshot_id=snapshot.id,
        diff_artifact=diff_artifact,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
        ssim_score=result.ssim_score,
        change_kind=change_kind,
        diff_metadata=diff_metadata,
        team_id=snapshot.team_id,
    )

    logger.info(
        "visual_review.diff_computed",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        change_kind=change_kind.value,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
        ssim_score=result.ssim_score,
        size_mismatch=result.size_mismatch,
        cluster_count=result.cluster_summary.total if result.cluster_summary else 0,
    )


def _diff_snapshot(snapshot: RunSnapshot) -> None:
    """Compare snapshot against baseline; classify and store diff metrics.

    Classification (in priority order):
    1. Pixel diff above threshold -> CHANGED, kind=pixel
    2. SSIM dissimilarity above threshold -> CHANGED, kind=structural
       (tall-page dilution safety net)
    3. Both below -> UNCHANGED (noise), auto-populate tolerance cache.

    Size mismatch is recorded as `diff_metadata.size_mismatch` and surfaced
    separately in the UI — a snapshot can have a different viewport AND a
    real content change, so we don't conflate the two.

    `diff_percentage` and `ssim_score` are recorded faithfully; the categorical
    kind is what callers use to render. No overwriting one signal with another.
    """
    from . import logic

    repo_id = snapshot.run.repo_id
    assert snapshot.baseline_artifact is not None
    assert snapshot.current_artifact is not None

    baseline_bytes = logic.read_artifact_bytes(repo_id, snapshot.baseline_artifact.content_hash)
    current_bytes = logic.read_artifact_bytes(repo_id, snapshot.current_artifact.content_hash)

    if not baseline_bytes or not current_bytes:
        logger.warning(
            "visual_review.diff_skipped_missing_artifact",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
            has_baseline=baseline_bytes is not None,
            has_current=current_bytes is not None,
        )
        return

    result = compare_images(baseline_bytes, current_bytes)

    _store_thumbnail(snapshot, result)

    kind = classify_compare_result(result)
    if kind is not None:
        _store_diff(snapshot, result, kind)
        return

    # Both tiers below threshold — genuine noise, reclassify and cache for future runs
    snapshot.result = SnapshotResult.UNCHANGED
    snapshot.classification_reason = ClassificationReason.BELOW_THRESHOLD
    snapshot.diff_percentage = result.diff_percentage
    snapshot.diff_pixel_count = result.diff_pixel_count
    snapshot.ssim_score = result.ssim_score
    snapshot.save(
        update_fields=["result", "classification_reason", "diff_percentage", "diff_pixel_count", "ssim_score"]
    )
    logger.info(
        "visual_review.diff_below_threshold",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.diff_percentage,
        ssim_score=result.ssim_score,
    )

    # Auto-populate tolerance cache so future runs skip diffing for this hash
    ToleratedHash.objects.get_or_create(
        repo_id=snapshot.run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
            "team_id": snapshot.team_id,
            "reason": ToleratedReason.AUTO_THRESHOLD,
            "source_run": snapshot.run,
            "diff_percentage": result.diff_percentage,
        },
    )


def _generate_thumbnail_for_new(snapshot: RunSnapshot) -> None:
    """Generate thumbnail for NEW snapshots (no baseline to compare against)."""
    from . import logic

    artifact = snapshot.current_artifact
    if artifact is None or artifact.thumbnail_id is not None:
        return

    current_bytes = logic.read_artifact_bytes(snapshot.run.repo_id, artifact.content_hash)
    if not current_bytes:
        return

    try:
        webp_bytes = pixelhog_thumbnail(current_bytes, width=THUMB_WIDTH, height=THUMB_HEIGHT)
    except Exception:
        logger.warning(
            "visual_review.thumbnail_generation_failed",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
        )
        return

    thumb_hash = blake3(webp_bytes).hexdigest()
    thumb_artifact = logic.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=thumb_hash,
        content=webp_bytes,
        width=THUMB_WIDTH,
        height=THUMB_HEIGHT,
        team_id=snapshot.team_id,
    )

    artifact.thumbnail = thumb_artifact
    artifact.save(update_fields=["thumbnail"])


def process_diffs(run_id: UUID) -> None:
    """
    Process diffs for all changed snapshots in a run.

    Uses single-pass comparison (pixelmatch + SSIM + thumbnail) to classify
    each snapshot and generate thumbnails for the grid view.
    """
    from . import logic

    snapshots = logic.get_run_snapshots(run_id)

    for snapshot in snapshots:
        if snapshot.result == SnapshotResult.NEW and snapshot.current_artifact:
            _generate_thumbnail_for_new(snapshot)

        if snapshot.result != SnapshotResult.CHANGED:
            continue

        if not snapshot.current_artifact or not snapshot.baseline_artifact:
            continue

        try:
            _diff_snapshot(snapshot)
        except Exception as e:
            logger.warning(
                "visual_review.snapshot_diff_failed",
                snapshot_id=str(snapshot.id),
                identifier=snapshot.identifier,
                error=str(e),
            )
