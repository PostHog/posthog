import structlog

from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)


def enqueue_turn_suggestion(task_run: TaskRun) -> bool:
    """Queue the end-of-turn suggestion for an interactive PostHog AI run. Never raises: the turn
    completion that calls this must not fail because a nudge could not be scheduled."""
    if task_run.mode != "interactive" or task_run.origin_product != Task.OriginProduct.POSTHOG_AI:
        return False
    from products.posthog_ai.backend.tasks import (
        generate_turn_suggestion_task,  # noqa: PLC0415 — the Celery task module imports this product's service layer, which imports the tasks facade; loading it here keeps the tasks stream hooks importable
    )

    try:
        generate_turn_suggestion_task.delay(run_id=str(task_run.id))
    except Exception:
        logger.warning("posthog_ai_turn_suggestion_enqueue_failed", run_id=str(task_run.id), exc_info=True)
        return False
    return True
