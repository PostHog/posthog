from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.batch_jobs import resume_batch_jobs_waiting_for_cohort


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    # The ready signal fires once and a resume is idempotent, so a task a dying worker held runs again.
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # The ready signal fires once, so the retries span the run's 24-hour wait at up to 10 minutes apart,
    # and a CDP API outage that ends before the deadline still wakes the run. Jitter would cut each wait
    # to a random fraction and end the retries after about 12 hours.
    retry_jitter=False,
    retry_backoff_max=600,
    max_retries=150,
)
@skip_team_scope_audit
def resume_batch_jobs_waiting_for_realtime_cohort(team_id: int, cohort_id: int) -> None:
    resume_batch_jobs_waiting_for_cohort(team_id=team_id, cohort_id=cohort_id)
