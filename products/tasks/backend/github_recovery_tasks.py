from django.db.models import Q
from django.utils import timezone

from asgiref.sync import async_to_sync
from celery import shared_task
from temporalio.service import RPCError, RPCStatusCode

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import with_team_scope
from posthog.temporal.common.client import async_connect

from products.tasks.backend.github_recovery import GITHUB_ACCESS_RESTORED_SIGNAL
from products.tasks.backend.models import Task, TaskRun


async def signal_github_access_restored(workflow_ids: list[str]) -> None:
    client = await async_connect()
    for workflow_id in workflow_ids:
        try:
            await client.get_workflow_handle(workflow_id).signal(GITHUB_ACCESS_RESTORED_SIGNAL)
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise


@shared_task(
    queue=CeleryQueue.LONG_RUNNING.value,
    ignore_result=True,
    soft_time_limit=240,
    time_limit=300,
    autoretry_for=(Exception,),
    retry_backoff=10,
    max_retries=5,
)
@with_team_scope()
def resume_github_blocked_implementations(team_id: int, after_run_id: str | None = None) -> None:
    runs = TaskRun.objects.filter(
        team_id=team_id,
        task__team_id=team_id,
        status=TaskRun.Status.QUEUED,
        environment=TaskRun.Environment.CLOUD,
        task__deleted=False,
        task__origin_product=Task.OriginProduct.SIGNAL_REPORT,
        task__signal_report_tasks__team_id=team_id,
        task__signal_report_tasks__relationship="implementation",
    ).filter(
        Q(state__github_recovery_deadline__isnull=True)
        | Q(state__github_recovery_deadline__gt=timezone.now().isoformat())
    )
    if after_run_id:
        runs = runs.filter(id__gt=after_run_id)
    batch = list(runs.order_by("id").distinct()[:25])
    if not batch:
        return
    # Signal queued runs even before their first access check records a blocker, so reconnects cannot race that check.
    async_to_sync(signal_github_access_restored)([run.workflow_id for run in batch])
    if len(batch) == 25:
        resume_github_blocked_implementations.delay(team_id, str(batch[-1].id))
