from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy

from posthog.temporal.common.client import async_connect


async def request_model_alias_reconciliation(team_id: int, saved_query_id: str | None = None) -> None:
    temporal = await async_connect()
    await temporal.start_workflow(
        "managed-warehouse.reconcile-model-aliases",
        {"team_id": team_id},
        id=f"managed-warehouse-model-aliases/{team_id}",
        task_queue=settings.DUCKLAKE_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        start_signal="refresh",
        start_signal_args=[saved_query_id],
    )
