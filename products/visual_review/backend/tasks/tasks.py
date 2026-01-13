"""
Celery tasks for visual_review.

Async entrypoints that call the facade (api/api.py).
Keep task functions thin - only call facade methods.
"""

from uuid import UUID

import structlog
from celery import shared_task

from .. import logic
from ..domain_types import SnapshotResult

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def process_run_diffs(run_id: str) -> None:
    """
    Process diffs for all snapshots in a run.

    Called after CI signals that all artifacts have been uploaded.
    """
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
    """
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

    TODO: Integrate Rust-based image diff engine.

    The Rust engine would:
    1. Download both images from S3
    2. Decode PNGs to raw RGBA
    3. Run pixelmatch algorithm
    4. Generate diff image
    5. Return diff metrics (percentage, pixel count)
    """
    # Placeholder - actual implementation will call Rust diff engine
    # via PyO3 bindings or subprocess
    #
    # Example future integration:
    # from visual_review_diff import compute_diff  # Rust PyO3 module
    # result = compute_diff(baseline_path, current_path)
    # logic.update_snapshot_diff(snapshot.id, result.diff_artifact, ...)
    logger.info(
        "visual_review.diff_skipped_not_implemented",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
    )
