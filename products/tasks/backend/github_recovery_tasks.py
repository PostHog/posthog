from django.utils import timezone

from asgiref.sync import async_to_sync
from celery import shared_task
from temporalio.service import RPCError, RPCStatusCode

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import with_team_scope
from posthog.temporal.common.client import async_connect

from products.tasks.backend.github_recovery import GITHUB_ACCESS_RESTORED_SIGNAL
from products.tasks.backend.models import Task, TaskRun


async def _signal_github_recovery(workflow_id: str) -> None:
    client = await async_connect()
    try:
        await client.get_workflow_handle(workflow_id).signal(GITHUB_ACCESS_RESTORED_SIGNAL)
    except RPCError as error:
        if error.status != RPCStatusCode.NOT_FOUND:
            raise


@shared_task(
    queue=CeleryQueue.DEFAULT.value,
    ignore_result=True,
    soft_time_limit=240,
    time_limit=300,
    autoretry_for=(RPCError,),
    retry_backoff=True,
    max_retries=3,
)
@with_team_scope()
def resume_github_blocked_task_runs(team_id: int, after_run_id: str | None = None) -> None:
    runs = TaskRun.objects.filter(
        team_id=team_id,
        status=TaskRun.Status.QUEUED,
        environment=TaskRun.Environment.CLOUD,
        task__origin_product=Task.OriginProduct.SIGNAL_REPORT,
        task__deleted=False,
        state__github_recovery_deadline__gt=timezone.now().isoformat(),
    )
    if after_run_id:
        runs = runs.filter(id__gt=after_run_id)
    batch = list(runs.order_by("id")[:25])
    for run in batch:
        async_to_sync(_signal_github_recovery)(run.workflow_id)
    if len(batch) == 25:
        resume_github_blocked_task_runs.apply_async(args=[team_id, str(batch[-1].id)], countdown=60)
