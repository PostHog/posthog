"""Start the provider import workflow from Django."""

from datetime import timedelta
from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy

from posthog.temporal.common.client import async_connect

from products.messaging.backend.temporal.inputs import ProviderImportWorkflowInputs

PROVIDER_IMPORT_WORKFLOW = "messaging-provider-import"

# Bounds the whole run, so a run stranded on a queue with no pollers closes instead of blocking new imports forever.
RUN_EXECUTION_TIMEOUT = timedelta(hours=24)


@async_to_sync
async def start_provider_import_workflow(team_id: int, run_id: UUID, steps: list[str]) -> None:
    client = await async_connect()
    await client.start_workflow(
        PROVIDER_IMPORT_WORKFLOW,
        ProviderImportWorkflowInputs(team_id=team_id, run_id=str(run_id), steps=steps),
        id=f"{PROVIDER_IMPORT_WORKFLOW}-{run_id}",
        task_queue=settings.MESSAGING_IMPORT_TASK_QUEUE,
        execution_timeout=RUN_EXECUTION_TIMEOUT,
        # Retries live on the activities. A workflow retry would run steps that already completed again.
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
