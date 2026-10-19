"""Removes the retired briefing schedule and its open runs. No worker registers their workflows any more."""

import structlog
from temporalio.client import Client

from posthog.temporal.common.schedule import a_delete_schedule, a_schedule_exists

logger = structlog.get_logger(__name__)

_SCHEDULE_ID = "today-briefing-scheduler"
_RETIRED_WORKFLOW_TYPES = ("today-generate-briefing", "today-briefing-scheduler")


async def delete_today_briefing_schedule(client: Client) -> None:
    if await a_schedule_exists(client, _SCHEDULE_ID):
        await a_delete_schedule(client, _SCHEDULE_ID)
    # A run without a registered workflow retries its workflow task until it times out, and a generate run has no
    # execution timeout. Remove this function with the table drop.
    types = " OR ".join(f'WorkflowType = "{workflow_type}"' for workflow_type in _RETIRED_WORKFLOW_TYPES)
    try:
        async for workflow in client.list_workflows(query=f'ExecutionStatus = "Running" AND ({types})'):
            await client.get_workflow_handle(workflow.id, run_id=workflow.run_id).terminate(
                reason="The Today briefing is retired."
            )
    except Exception:
        # Best effort: a failure here must not stop the rest of schedule setup.
        logger.exception("today_briefing_run_terminate_failed")
