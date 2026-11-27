"""Rebuilds the stored highlight feeds of teams whose ranks changed."""

import datetime as dt
from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    HIGHLIGHT_REBUILD_ACTIVITY_TIMEOUT,
    HIGHLIGHT_REBUILD_EXECUTION_TIMEOUT,
    HIGHLIGHT_REBUILD_HEARTBEAT_TIMEOUT,
    HIGHLIGHT_REBUILD_INTERVAL,
    HIGHLIGHT_REBUILD_SCHEDULE_ID,
    HIGHLIGHT_REBUILD_WORKFLOW_ID,
    HIGHLIGHT_REBUILD_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.highlight_rebuild_types import (
    RebuildHighlightFeedsInputs,
    RebuildHighlightFeedsResult,
)

if TYPE_CHECKING:
    from temporalio.client import Client

# `activities` pulls in Django, which the workflow sandbox can't safely re-import.
with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities.rebuild_highlight_feeds import (
        rebuild_highlight_feeds_activity,
    )


@workflow.defn(name=HIGHLIGHT_REBUILD_WORKFLOW_NAME)
class RebuildHighlightFeedsWorkflow(PostHogWorkflow):
    inputs_cls = RebuildHighlightFeedsInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: RebuildHighlightFeedsInputs) -> RebuildHighlightFeedsResult:
        # No retry: the schedule starts the next run a minute later, and it picks up whatever this one left.
        return await workflow.execute_activity(
            rebuild_highlight_feeds_activity,
            start_to_close_timeout=HIGHLIGHT_REBUILD_ACTIVITY_TIMEOUT,
            heartbeat_timeout=HIGHLIGHT_REBUILD_HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


async def create_replay_vision_highlight_rebuild_schedule(client: "Client") -> None:
    """Upsert the per-minute highlight feed rebuild schedule. Called on worker startup."""
    # Function-local: with `@workflow.defn` above, the Temporal sandbox can't re-import the helper's dependencies.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=HIGHLIGHT_REBUILD_SCHEDULE_ID,
        workflow_name=HIGHLIGHT_REBUILD_WORKFLOW_NAME,
        workflow_id=HIGHLIGHT_REBUILD_WORKFLOW_ID,
        inputs=RebuildHighlightFeedsInputs(),
        interval=HIGHLIGHT_REBUILD_INTERVAL,
        offset=dt.timedelta(0),
        execution_timeout=HIGHLIGHT_REBUILD_EXECUTION_TIMEOUT,
    )
