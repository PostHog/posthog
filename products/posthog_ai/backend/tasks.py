import structlog
from celery import Task, shared_task
from prometheus_client import Counter

from posthog.celery_queues import CeleryQueue

from products.posthog_ai.backend.reply_suggestions.service import generate_reply_suggestions
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


REPLY_SUGGESTIONS_OUTCOMES_TOTAL = Counter(
    "posthog_ai_reply_suggestions_outcomes_total",
    "End-of-turn reply suggestion jobs by outcome",
    labelnames=["status", "reason"],
)


REPLY_SUGGESTIONS_SETTLE_RETRIES = 6
REPLY_SUGGESTIONS_SETTLE_RETRY_SECONDS = 0.5


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.POSTHOG_AI.value,
    soft_time_limit=45,
    time_limit=60,
    max_retries=REPLY_SUGGESTIONS_SETTLE_RETRIES,
)
def generate_reply_suggestions_task(self: Task, *, run_id: str, team_id: int) -> None:
    outcome = generate_reply_suggestions(run_id, team_id)
    if outcome.reason == "turn_in_progress" and self.request.retries < REPLY_SUGGESTIONS_SETTLE_RETRIES:
        raise self.retry(countdown=REPLY_SUGGESTIONS_SETTLE_RETRY_SECONDS)
    reason = outcome.reason if outcome.status != "emitted" else "emitted"
    REPLY_SUGGESTIONS_OUTCOMES_TOTAL.labels(status=outcome.status, reason=reason).inc()
    logger.info(
        "posthog_ai_reply_suggestions_outcome",
        run_id=run_id,
        team_id=team_id,
        status=outcome.status,
        reason=outcome.reason,
    )
