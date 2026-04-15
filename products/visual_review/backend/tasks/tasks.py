"""
Celery tasks for visual_review.

Async entrypoints that call business logic.
Keep task functions thin — only call logic/diffing methods.

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
    from ..diffing import process_diffs

    run_uuid = UUID(run_id)

    try:
        logger.info("visual_review.diff_processing_started", run_id=run_id)
        process_diffs(run_uuid)
        logic.mark_run_completed(run_uuid)
        logger.info("visual_review.diff_processing_completed", run_id=run_id)
    except Exception as e:
        logger.exception("visual_review.diff_processing_failed", run_id=run_id, error=str(e))
        logic.mark_run_completed(run_uuid, error_message=str(e))
        raise
