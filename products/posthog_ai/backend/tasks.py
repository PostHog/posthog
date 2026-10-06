import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.celery_queues import CeleryQueue

from products.posthog_ai.backend.turn_suggestions.service import generate_turn_suggestion

logger = structlog.get_logger(__name__)

TURN_SUGGESTION_OUTCOMES_TOTAL = Counter(
    "posthog_ai_turn_suggestion_outcomes_total",
    "End-of-turn suggestion jobs by outcome, so a gate that skips every turn in a region shows up",
    labelnames=["status", "reason"],
)


# No retries: a suggestion that misses its turn is worth less than a stale one arriving mid-conversation.
@shared_task(ignore_result=True, queue=CeleryQueue.POSTHOG_AI.value, soft_time_limit=90, time_limit=120)
def generate_turn_suggestion_task(*, run_id: str, team_id: int) -> None:
    outcome = generate_turn_suggestion(run_id, team_id)
    TURN_SUGGESTION_OUTCOMES_TOTAL.labels(status=outcome.status, reason=outcome.reason).inc()
    logger.info(
        "posthog_ai_turn_suggestion_outcome",
        run_id=run_id,
        team_id=team_id,
        status=outcome.status,
        reason=outcome.reason,
    )
