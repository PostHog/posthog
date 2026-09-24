from typing import TYPE_CHECKING, Any

import structlog

from posthog.redis import get_client

from products.tasks.backend.facade.task_run_signals import TaskOriginProduct

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)

# The proxy callback, the event ingest and the sandbox relay can each report the same turn, within
# moments of each other. A person cannot finish two turns this close together.
ENQUEUE_DEDUP_SECONDS = 5
# The proxy callback reports over its own channel and can beat the ingest writes of the turn's last
# frames, so the read waits for them instead of judging a turn whose answer has not landed.
TURN_SETTLE_SECONDS = 2


def _enqueue_dedup_key(run_id: str) -> str:
    return f"turn_suggestion:{run_id}"


def _first_report_of_turn(run_id: str) -> bool:
    try:
        return bool(get_client().set(_enqueue_dedup_key(run_id), 1, nx=True, ex=ENQUEUE_DEDUP_SECONDS))
    except Exception:
        # The offer ledger still refuses a second claim of the same turn, so a duplicate only costs a read.
        logger.warning("posthog_ai_turn_suggestion_dedup_failed", run_id=run_id, exc_info=True)
        return True


def enqueue_turn_suggestion(task_run: "TaskRun") -> bool:
    """Queue the end-of-turn suggestion for a PostHog AI run. Never raises: the turn completion that
    calls this must not fail because a nudge could not be scheduled."""
    try:
        if task_run.origin_product != TaskOriginProduct.POSTHOG_AI:
            return False
        run_id = str(task_run.id)
        if not _first_report_of_turn(run_id):
            return False
        from products.posthog_ai.backend.tasks import (
            generate_turn_suggestion_task,  # noqa: PLC0415 — keeps the judge and drafter clients off the Django startup path
        )

        generate_turn_suggestion_task.apply_async(
            kwargs={"run_id": run_id, "team_id": task_run.team_id}, countdown=TURN_SETTLE_SECONDS
        )
    except Exception:
        logger.warning("posthog_ai_turn_suggestion_enqueue_failed", run_id=str(task_run.id), exc_info=True)
        return False
    return True


def enqueue_turn_suggestion_on_turn_completed(sender: type, task_run: "TaskRun", **kwargs: Any) -> None:
    enqueue_turn_suggestion(task_run)
