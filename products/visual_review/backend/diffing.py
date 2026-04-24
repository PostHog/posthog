"""
Diff processing and two-tier classification for visual review.

Orchestrates pixel-level diff (pixelhog) and structural similarity (SSIM)
to classify snapshots as genuinely changed or rendering noise. Stores
diff artifacts and updates snapshot state.

Called by the Celery task; all business logic lives here.
"""

from uuid import UUID

import structlog

from .diff import compute_diff
from .facade.enums import ClassificationReason, SnapshotResult, ToleratedReason
from .models import RunSnapshot, ToleratedHash
from .ssim import compute_ssim

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
PIXEL_DIFF_THRESHOLD_PERCENT = 1.0
SSIM_DISSIMILARITY_THRESHOLD = 0.01  # 1% structural difference


def _store_diff(snapshot: RunSnapshot, result, *, ssim_score: float | None = None) -> None:
    """Upload diff artifact and update snapshot metrics."""
    from . import logic

    diff_artifact = logic.write_artifact_bytes(
        repo_id=snapshot.run.repo_id,
        content_hash=result.diff_hash,
        content=result.diff_image,
        width=result.width,
        height=result.height,
        team_id=snapshot.team_id,
    )

    logic.update_snapshot_diff(
        snapshot_id=snapshot.id,
        diff_artifact=diff_artifact,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
        team_id=snapshot.team_id,
    )

    logger.info(
        "visual_review.diff_computed",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
        ssim_score=ssim_score,
    )


def _diff_snapshot(snapshot: RunSnapshot) -> None:
    """
    Compute diff between baseline and current artifact.

    Two-tier classification:
    1. Pixel diff ratio above threshold → CHANGED (skip SSIM).
    2. Below pixel threshold → run SSIM. Above SSIM threshold → CHANGED
       (tall-page dilution case). Below both → UNCHANGED (noise).

    Pixel diff always runs to produce the diff visualization image.
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

    result = compute_diff(baseline_bytes, current_bytes)

    if result.diff_percentage >= PIXEL_DIFF_THRESHOLD_PERCENT:
        _store_diff(snapshot, result)
        return

    # Pixel diff says below threshold — check SSIM for tall-page dilution
    ssim_score = compute_ssim(baseline_bytes, current_bytes)
    ssim_dissimilarity = 1.0 - ssim_score

    if ssim_dissimilarity >= SSIM_DISSIMILARITY_THRESHOLD:
        # Store SSIM dissimilarity as the diff percentage — it's the metric
        # that decided this snapshot is changed, so it's more meaningful
        # than the diluted pixel ratio.
        result.diff_percentage = round(ssim_dissimilarity * 100, 4)
        result.diff_pixel_count = 0
        _store_diff(snapshot, result, ssim_score=ssim_score)
        logger.info(
            "visual_review.diff_caught_by_ssim",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
            diff_percentage=result.diff_percentage,
            ssim_dissimilarity=round(ssim_dissimilarity, 4),
        )
        return

    # Both below threshold — genuine noise, reclassify and cache for future runs
    snapshot.result = SnapshotResult.UNCHANGED
    snapshot.classification_reason = ClassificationReason.BELOW_THRESHOLD
    snapshot.diff_percentage = result.diff_percentage
    snapshot.diff_pixel_count = result.diff_pixel_count
    snapshot.save(update_fields=["result", "classification_reason", "diff_percentage", "diff_pixel_count"])
    logger.info(
        "visual_review.diff_below_threshold",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.diff_percentage,
        ssim_dissimilarity=round(ssim_dissimilarity, 4),
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


def process_diffs(run_id: UUID) -> None:
    """
    Process diffs for all changed snapshots in a run.

    Uses two-tier classification (pixel diff + SSIM) to decide whether
    each snapshot is a real change or rendering noise.
    """
    from . import logic

    snapshots = logic.get_run_snapshots(run_id)

    for snapshot in snapshots:
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
