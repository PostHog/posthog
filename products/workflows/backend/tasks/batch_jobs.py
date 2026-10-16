from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.batch_jobs import dispatch_batch_jobs_waiting_for_cohorts


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def dispatch_batch_jobs_waiting_for_realtime_cohorts() -> None:
    dispatch_batch_jobs_waiting_for_cohorts()
