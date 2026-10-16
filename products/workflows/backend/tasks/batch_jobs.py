from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.batch_jobs import resume_batch_jobs_waiting_for_cohort


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@skip_team_scope_audit
def resume_batch_jobs_waiting_for_realtime_cohort(team_id: int, cohort_id: int) -> None:
    resume_batch_jobs_waiting_for_cohort(team_id=team_id, cohort_id=cohort_id)
