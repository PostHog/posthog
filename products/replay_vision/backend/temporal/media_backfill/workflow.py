import asyncio

import temporalio.workflow as wf
from temporalio import common
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY

from products.replay_vision.backend.temporal.media_backfill.constants import (
    FIND_CANDIDATES_TIMEOUT,
    MEDIA_CHILD_EXECUTION_TIMEOUT,
    WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.media_backfill.types import MediaBackfillCandidate, MediaBackfillInputs

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from products.replay_vision.backend.temporal.media_backfill.activities import (
        find_media_backfill_candidates_activity,
    )
    from products.replay_vision.backend.temporal.media_types import (
        MEDIA_WORKFLOW_NAME,
        ObservationMediaInputs,
        build_media_workflow_id,
    )


@wf.defn(name=WORKFLOW_NAME)
class ReplayVisionMediaBackfillWorkflow(PostHogWorkflow):
    """Give a poster to succeeded observations that have none.

    Catch-up for observations scanned before media existed, and repair for renders the fail-soft
    media path dropped. The moment comes from the stored scanner result: the model's own pick is
    long gone, so these fall back to a citation or a quarter of the way in.
    """

    inputs_cls = MediaBackfillInputs
    inputs_optional = True

    @wf.run
    async def run(self, inputs: MediaBackfillInputs) -> int:
        found = await wf.execute_activity(
            find_media_backfill_candidates_activity,
            inputs,
            start_to_close_timeout=FIND_CANDIDATES_TIMEOUT,
            # A failed tick is not worth retrying: the next one is five minutes away.
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )
        if not found.candidates:
            return 0

        started = await asyncio.gather(*(self._start(c) for c in found.candidates))
        return sum(started)

    async def _start(self, candidate: MediaBackfillCandidate) -> bool:
        try:
            await wf.start_child_workflow(
                MEDIA_WORKFLOW_NAME,
                ObservationMediaInputs(
                    team_id=candidate.team_id,
                    observation_id=candidate.observation_id,
                    session_id=candidate.session_id,
                    analysis_asset_id=candidate.analysis_asset_id,
                ),
                # The id the live path uses, so a scan already rendering this wins and the sweep skips it.
                id=build_media_workflow_id(candidate.observation_id),
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
                execution_timeout=MEDIA_CHILD_EXECUTION_TIMEOUT,
                # Without these a backfilled render is not findable by team in the Temporal UI.
                search_attributes=TypedSearchAttributes(
                    search_attributes=[
                        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=candidate.team_id),
                        SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=candidate.session_id),
                    ]
                ),
            )
            return True
        except WorkflowAlreadyStartedError:
            return False
        except Exception as error:
            # One observation must never sink the tick.
            wf.logger.warning("replay_vision.media_backfill.start_failed", extra={"error": str(error)})
            return False
