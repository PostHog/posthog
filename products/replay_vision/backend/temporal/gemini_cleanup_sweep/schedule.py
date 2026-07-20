from temporalio.client import Client
from temporalio.common import SearchAttributePair, TypedSearchAttributes

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.replay_vision.backend.temporal.gemini_cleanup_sweep.constants import (
    SCHEDULE_ID,
    SCHEDULE_INTERVAL,
    SCHEDULE_TYPE,
    WORKFLOW_EXECUTION_TIMEOUT,
    WORKFLOW_ID,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.types import CleanupSweepInputs
from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule


async def create_replay_vision_gemini_cleanup_sweep_schedule(client: Client) -> None:
    await upsert_interval_schedule(
        client,
        schedule_id=SCHEDULE_ID,
        workflow_name=WORKFLOW_NAME,
        workflow_id=WORKFLOW_ID,
        inputs=CleanupSweepInputs(),
        interval=SCHEDULE_INTERVAL,
        execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        search_attributes=TypedSearchAttributes(
            search_attributes=[SearchAttributePair(key=POSTHOG_SCHEDULE_TYPE_KEY, value=SCHEDULE_TYPE)]
        ),
    )
