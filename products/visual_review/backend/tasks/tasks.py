"""
Celery tasks for visual_review.

Async entrypoints that call the facade (api/api.py).
Keep task functions thin - only call facade methods.

NOTE: Imports are done inside functions to avoid circular imports
when Celery loads this module at startup.
"""

from uuid import UUID

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)

# Two-tier classification thresholds:
#
# 1. Pixelmatch pixel ratio — fast path for obvious changes. Snapshots above
#    this are immediately classified as CHANGED.
# 2. SSIM perceptual threshold — safety net for tall-page dilution. A real UI
#    change at the bottom of a long screenshot affects few pixels but produces
#    a measurable structural shift that SSIM catches.
#
# Only when both are below threshold is the snapshot reclassified as UNCHANGED.
PIXEL_DIFF_THRESHOLD_PERCENT = 1.0
SSIM_DISSIMILARITY_THRESHOLD = 0.01  # 1% structural difference


@shared_task(name="products.visual_review.backend.tasks.process_run_diffs", ignore_result=True)
def process_run_diffs(run_id: str) -> None:
    """
    Process diffs for all snapshots in a run.

    Called after CI signals that all artifacts have been uploaded.
    """
    from .. import logic

    run_uuid = UUID(run_id)

    try:
        logger.info("visual_review.diff_processing_started", run_id=run_id)
        _process_diffs(run_uuid)
        logic.mark_run_completed(run_uuid)
        logger.info("visual_review.diff_processing_completed", run_id=run_id)
    except Exception as e:
        logger.exception("visual_review.diff_processing_failed", run_id=run_id, error=str(e))
        logic.mark_run_completed(run_uuid, error_message=str(e))
        raise


def _process_diffs(run_id: UUID) -> None:
    """
    Process diffs for all changed snapshots in a run.

    Uses two-tier classification (pixelmatch + SSIM) to decide whether
    each snapshot is a real change or rendering noise.
    """
    from .. import logic
    from ..facade.enums import SnapshotResult

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


def _diff_snapshot(snapshot) -> None:
    """
    Compute diff between baseline and current artifact.

    Two-tier classification:
    1. Pixelmatch pixel ratio above threshold → CHANGED (skip SSIM).
    2. Below pixel threshold → run SSIM. Above SSIM threshold → CHANGED
       (tall-page dilution case). Below both → UNCHANGED (noise).

    Pixelmatch always runs to produce the diff visualization image.
    """
    from .. import logic
    from ..diff import compute_diff
    from ..facade.enums import SnapshotResult
    from ..ssim import compute_ssim

    repo_id = snapshot.run.repo_id

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

    # Pixelmatch says below threshold — check SSIM for tall-page dilution
    ssim_score = compute_ssim(baseline_bytes, current_bytes)
    ssim_dissimilarity = 1.0 - ssim_score

    if ssim_dissimilarity >= SSIM_DISSIMILARITY_THRESHOLD:
        _store_diff(snapshot, result, ssim_score=ssim_score)
        logger.info(
            "visual_review.diff_caught_by_ssim",
            snapshot_id=str(snapshot.id),
            identifier=snapshot.identifier,
            diff_percentage=result.diff_percentage,
            ssim_dissimilarity=round(ssim_dissimilarity, 4),
        )
        return

    # Both below threshold — genuine noise
    snapshot.result = SnapshotResult.UNCHANGED
    snapshot.diff_percentage = result.diff_percentage
    snapshot.diff_pixel_count = result.diff_pixel_count
    snapshot.save(update_fields=["result", "diff_percentage", "diff_pixel_count"])
    logger.info(
        "visual_review.diff_below_threshold",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.diff_percentage,
        ssim_dissimilarity=round(ssim_dissimilarity, 4),
    )


def _store_diff(snapshot, result, *, ssim_score: float | None = None) -> None:
    """Upload diff artifact and update snapshot metrics."""
    from .. import logic

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
