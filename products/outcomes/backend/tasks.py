from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import with_team_scope

from products.outcomes.backend.evaluation import evaluate_outcome
from products.outcomes.backend.models import Outcome

# Crash recovery is "run again": evaluation is stateless between runs and latching is
# idempotent, so there is no retry logic here — the next scheduled run repairs any gap.


@shared_task(ignore_result=True)
def schedule_outcome_calculations() -> None:
    """Periodic entrypoint: fan out one calculation task per outcome definition."""
    for outcome_id, team_id in Outcome.objects.unscoped().values_list("id", "team_id"):
        calculate_outcome.delay(outcome_id=str(outcome_id), team_id=team_id)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@with_team_scope()
def calculate_outcome(outcome_id: str, team_id: int) -> None:
    """Evaluate a single outcome against its team's events, latching and emitting new facts."""
    outcome = Outcome.objects.filter(id=outcome_id, team_id=team_id).first()
    if outcome is None:
        return
    evaluate_outcome(outcome)
