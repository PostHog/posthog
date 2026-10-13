from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.data_suggestions.service import run_data_suggestions


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def generate_data_suggestions(team_id: int, user_id: int) -> None:
    run_data_suggestions(team_id=team_id, user_id=user_id)
