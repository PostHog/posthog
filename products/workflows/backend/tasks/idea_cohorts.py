from celery import shared_task
from structlog import get_logger

from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.idea_cohorts import rotate_idea_cohort

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
def rotate_workflow_idea_cohort() -> None:
    """End due trials of the workflow ideas scout and start the next cohort. Off unless the
    `workflow-ideas-cohorts` flag payload turns it on."""
    result = rotate_idea_cohort()
    if result.ended or result.started:
        logger.info("workflow_idea_cohort_rotated", ended=result.ended, started=result.started, cohort=result.cohort)
