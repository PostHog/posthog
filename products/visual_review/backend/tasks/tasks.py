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
    """
    from .. import logic
    from ..domain_types import SnapshotResult

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

    Downloads both images, computes pixel diff, uploads diff image.
    """
    from .. import logic
    from ..diff import compute_diff

    repo_id = snapshot.run.repo_id

    # Download images from storage
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

    # Compute diff
    result = compute_diff(baseline_bytes, current_bytes)

    # Upload diff image
    diff_artifact = logic.write_artifact_bytes(
        repo_id=repo_id,
        content_hash=result.diff_hash,
        content=result.diff_image,
        width=result.width,
        height=result.height,
    )

    # Update snapshot with diff results
    logic.update_snapshot_diff(
        snapshot_id=snapshot.id,
        diff_artifact=diff_artifact,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
    )

    logger.info(
        "visual_review.diff_computed",
        snapshot_id=str(snapshot.id),
        identifier=snapshot.identifier,
        diff_percentage=result.diff_percentage,
        diff_pixel_count=result.diff_pixel_count,
    )
