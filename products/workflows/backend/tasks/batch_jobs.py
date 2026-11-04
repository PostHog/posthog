from django.db import DatabaseError

from celery import Task, shared_task

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.batch_audience_snapshot import (
    AUDIENCE_QUERY_TRANSIENT_ERRORS,
    audience_failure_reason,
    delete_audience_snapshot,
    record_audience_snapshot_failure,
    resolve_audience_snapshot,
)
from products.workflows.backend.services.batch_jobs import resume_batch_jobs_waiting_for_cohort
from products.workflows.backend.services.batch_run_outcome import settle_batch_job_outcome

# The first check waits for the child runs of a small audience to execute and for their metrics to
# reach ClickHouse. Later checks follow at a fixed interval, and the check gives up waiting after a day.
BATCH_RUN_SETTLE_FIRST_CHECK_SECONDS = 5 * 60
BATCH_RUN_SETTLE_CHECK_INTERVAL_SECONDS = 10 * 60
BATCH_RUN_SETTLE_MAX_RETRIES = 24 * 6


class BatchRunNotSettled(Exception):
    pass


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


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    # The run parks until this finishes, so a task a dying worker held runs again instead of waiting out the deadline.
    acks_late=True,
    reject_on_worker_lost=True,
    # Failures that clear on their own escape here; the query's other failures are recorded on the run.
    autoretry_for=(DatabaseError, *AUDIENCE_QUERY_TRANSIENT_ERRORS),
    # Seconds apart, a ClickHouse capacity error would still be there on every retry.
    retry_backoff=30,
    max_retries=3,
)
@skip_team_scope_audit
def resolve_batch_job_audience_snapshot(
    self: Task, team_id: int, batch_job_id: str, dedupe_key: str | None, max_audience_size: int
) -> None:
    try:
        resolve_audience_snapshot(
            team_id=team_id, batch_job_id=batch_job_id, dedupe_key=dedupe_key, max_audience_size=max_audience_size
        )
    except (DatabaseError, *AUDIENCE_QUERY_TRANSIENT_ERRORS) as error:
        # Without this the run waits out the resolver's two-hour limit for an audience nothing resolves.
        if self.request.retries >= self.max_retries:
            record_audience_snapshot_failure(
                team_id=team_id, batch_job_id=batch_job_id, reason=audience_failure_reason(error)
            )
        raise


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
@skip_team_scope_audit
def delete_batch_job_audience_snapshot(team_id: int, batch_job_id: str) -> None:
    delete_audience_snapshot(team_id=team_id, batch_job_id=batch_job_id)


@shared_task(
    bind=True,
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    # A check only reads metrics and makes a conditional write, so a task a dying worker held runs again.
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=False,
    default_retry_delay=BATCH_RUN_SETTLE_CHECK_INTERVAL_SECONDS,
    max_retries=BATCH_RUN_SETTLE_MAX_RETRIES,
)
@skip_team_scope_audit
def settle_batch_run_outcome(self: Task, team_id: int, batch_job_id: str) -> None:
    final_check = self.request.retries >= BATCH_RUN_SETTLE_MAX_RETRIES
    if not settle_batch_job_outcome(team_id=team_id, batch_job_id=batch_job_id, final_check=final_check):
        raise BatchRunNotSettled(batch_job_id)


def schedule_batch_run_settle(*, team_id: int, batch_job_id: str) -> None:
    settle_batch_run_outcome.apply_async(args=(team_id, batch_job_id), countdown=BATCH_RUN_SETTLE_FIRST_CHECK_SECONDS)
