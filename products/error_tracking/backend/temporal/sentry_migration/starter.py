from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.temporal.sentry_migration.constants import WORKFLOW_ID_PREFIX
from products.error_tracking.backend.temporal.sentry_migration.types import SentryMigrationInputs
from products.error_tracking.backend.temporal.sentry_migration.workflow import SentryMigrationWorkflow


async def start_sentry_migration_workflow(*, migration_id: str, team_id: int) -> tuple[str, str | None]:
    client = await async_connect()
    workflow_id = f"{WORKFLOW_ID_PREFIX}-{team_id}-{migration_id}"
    handle = await client.start_workflow(
        SentryMigrationWorkflow.run,
        SentryMigrationInputs(migration_id=migration_id, team_id=team_id),
        id=workflow_id,
        task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    return workflow_id, handle.run_id
