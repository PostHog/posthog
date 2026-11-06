from typing import TYPE_CHECKING, Any

from django.core.cache import cache

import structlog

from products.tasks.backend.facade.task_run_signals import TaskOriginProduct

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

ENQUEUE_DEDUP_SECONDS = 1
REPLY_SUGGESTIONS_EXPIRES_SECONDS = 30


def enqueue_reply_suggestions(task_run: "TaskRun") -> bool:
    try:
        if task_run.origin_product != TaskOriginProduct.POSTHOG_AI:
            return False
        run_id = str(task_run.id)
        reservation = f"posthog_ai_reply_suggestions_enqueue:{run_id}"
        if not cache.add(reservation, True, timeout=ENQUEUE_DEDUP_SECONDS):
            return False
        from products.posthog_ai.backend.tasks import generate_reply_suggestions_task  # noqa: PLC0415

        try:
            generate_reply_suggestions_task.apply_async(
                kwargs={"run_id": run_id, "team_id": task_run.team_id},
                expires=REPLY_SUGGESTIONS_EXPIRES_SECONDS,
            )
        except Exception:
            cache.delete(reservation)
            raise
    except Exception:
        logger.warning("posthog_ai_reply_suggestions_enqueue_failed", run_id=str(task_run.id), exc_info=True)
        return False
    return True


def enqueue_reply_suggestions_on_turn_completed(sender: type, task_run: "TaskRun", **kwargs: Any) -> None:
    enqueue_reply_suggestions(task_run)
