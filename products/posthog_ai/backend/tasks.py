from celery import shared_task

from products.posthog_ai.backend.turn_suggestions.service import generate_turn_suggestion


# No retries: a suggestion that misses its turn is worth less than a stale one arriving mid-conversation.
@shared_task(ignore_result=True, soft_time_limit=90, time_limit=120)
def generate_turn_suggestion_task(*, run_id: str) -> None:
    generate_turn_suggestion(run_id)
