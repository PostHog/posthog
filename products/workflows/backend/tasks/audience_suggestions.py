from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.audience_suggestions.service import run_audience_suggestions


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def generate_audience_suggestions(team_id: int, user_id: int, lock_token: str) -> None:
    run_audience_suggestions(team_id=team_id, user_id=user_id, lock_token=lock_token)
