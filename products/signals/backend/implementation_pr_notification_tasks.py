from celery import Task, shared_task

from posthog.models.scoping import with_team_scope

from products.signals.backend.slack_report_threads import (
    ImplementationPRNotificationRetry,
    dispatch_implementation_pr_notifications,
)


@shared_task(
    name="products.signals.backend.tasks.deliver_implementation_pr_notifications",
    bind=True,
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=5,
    soft_time_limit=210,
    time_limit=240,
)
@with_team_scope()
def deliver_implementation_pr_notifications(self: Task, team_id: int, task_id: str, pr_url: str) -> None:
    try:
        dispatch_implementation_pr_notifications(team_id=team_id, task_id=task_id, pr_url=pr_url)
    except ImplementationPRNotificationRetry as error:
        raise self.retry(exc=error, countdown=max(min(60 * 2**self.request.retries, 3600), error.retry_after))
