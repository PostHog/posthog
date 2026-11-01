"""Moves scanner scouts that still carry a template's text onto the template's latest version."""

import datetime as dt
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    SCOUT_TEMPLATE_SYNC_ACTIVITY_TIMEOUT,
    SCOUT_TEMPLATE_SYNC_EXECUTION_TIMEOUT,
    SCOUT_TEMPLATE_SYNC_INTERVAL,
    SCOUT_TEMPLATE_SYNC_SCHEDULE_ID,
    SCOUT_TEMPLATE_SYNC_WORKFLOW_ID,
    SCOUT_TEMPLATE_SYNC_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.scout_template_sync_types import (
    SyncScoutTemplatesInputs,
    SyncScoutTemplatesResult,
)

if TYPE_CHECKING:
    from temporalio.client import Client

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities.sync_scout_templates import sync_scout_templates_activity


@workflow.defn(name=SCOUT_TEMPLATE_SYNC_WORKFLOW_NAME)
class SyncScoutTemplatesWorkflow(PostHogWorkflow):
    inputs_cls = SyncScoutTemplatesInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: SyncScoutTemplatesInputs) -> SyncScoutTemplatesResult:
        # No retry: the next scheduled run repeats the whole pass, and every write is a no-op once applied.
        return await workflow.execute_activity(
            sync_scout_templates_activity,
            start_to_close_timeout=SCOUT_TEMPLATE_SYNC_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


async def create_replay_vision_scout_template_sync_schedule(client: "Client") -> None:
    """Upsert the hourly scout template sync schedule. Called on worker startup."""
    # Function-local: with `@workflow.defn` above, the Temporal sandbox can't re-import the helper's dependencies.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=SCOUT_TEMPLATE_SYNC_SCHEDULE_ID,
        workflow_name=SCOUT_TEMPLATE_SYNC_WORKFLOW_NAME,
        workflow_id=SCOUT_TEMPLATE_SYNC_WORKFLOW_ID,
        inputs=SyncScoutTemplatesInputs(),
        interval=SCOUT_TEMPLATE_SYNC_INTERVAL,
        offset=dt.timedelta(0),
        execution_timeout=SCOUT_TEMPLATE_SYNC_EXECUTION_TIMEOUT,
    )
