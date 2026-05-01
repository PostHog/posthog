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

from ..logic import HashIntegrityError

logger = structlog.get_logger(__name__)


@shared_task(
    name="products.visual_review.backend.tasks.process_run_diffs",
    bind=True,
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def process_run_diffs(self, run_id: str) -> None:
    """
    Verify uploads, create artifacts, and process diffs for a run.

    Called after CI signals that all artifacts have been uploaded.
    Verifies hash integrity of new uploads before creating Artifact
    records and computing diffs.
    """
    from posthog.models.integration import GitHubRateLimitError

    from .. import logic
    from ..diffing import process_diffs

    run_uuid = UUID(run_id)

    try:
        logger.info("visual_review.diff_processing_started", run_id=run_id)
        logic.verify_uploads_and_create_artifacts(run_uuid)
        process_diffs(run_uuid)
        logic.finish_processing(run_uuid)
        logger.info("visual_review.diff_processing_completed", run_id=run_id)
    except HashIntegrityError as e:
        logger.warning("visual_review.hash_integrity_failed", run_id=run_id, error=str(e))
        logic.finish_processing(run_uuid, error_message=str(e))
    except GitHubRateLimitError as e:
        logger.warning(
            "visual_review.diff_processing_rate_limited",
            run_id=run_id,
            retry=self.request.retries,
            max_retries=self.max_retries,
        )
        try:
            countdown = e.retry_after or 60
            self.retry(countdown=min(countdown, 600), exc=e)
        except self.MaxRetriesExceededError:
            logic.finish_processing(run_uuid, error_message="GitHub API rate limit exceeded after retries")
    except Exception as e:
        logger.exception("visual_review.diff_processing_failed", run_id=run_id, error=str(e))
        logic.finish_processing(run_uuid, error_message=str(e))
        raise
