import datetime as dt

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow

with wf.unsafe.imports_passed_through():
    from django.conf import settings

    from products.replay_vision.backend.temporal.activities.observation_media import (
        finalize_observation_thumbnail_activity,
        prepare_observation_thumbnail_activity,
    )
    from products.replay_vision.backend.temporal.constants import STATE_ACTIVITY_RETRY, STATE_ACTIVITY_SCHEDULE_TO_CLOSE
    from products.replay_vision.backend.temporal.media_types import (
        MEDIA_WORKFLOW_NAME,
        THUMBNAIL_SCHEDULE_TO_CLOSE,
        ExtractThumbnailActivityOutput,
        FinalizeObservationThumbnailInputs,
        ObservationMediaInputs,
        PrepareObservationThumbnailOutput,
    )

_THUMBNAIL_TIMEOUT = dt.timedelta(minutes=5)
# Nothing retries a lost poster later, so this chain has to outlast a rasterizer backlog or outage.
_THUMBNAIL_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=20),
    backoff_coefficient=3.0,
    maximum_interval=dt.timedelta(minutes=15),
)


@wf.defn(name=MEDIA_WORKFLOW_NAME)
class ObservationMediaWorkflow(PostHogWorkflow):
    """Render the media that illustrates one succeeded observation. Today that is a single thumbnail."""

    inputs_cls = ObservationMediaInputs

    @wf.run
    async def run(self, inputs: ObservationMediaInputs) -> None:
        prepared: PrepareObservationThumbnailOutput = await wf.execute_activity(
            prepare_observation_thumbnail_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=30),
            schedule_to_close_timeout=STATE_ACTIVITY_SCHEDULE_TO_CLOSE,
            retry_policy=STATE_ACTIVITY_RETRY,
        )

        raw_result = await wf.execute_activity(
            "extract-thumbnail",
            prepared.activity_input.model_dump(exclude_none=True),
            task_queue=settings.RASTERIZATION_TASK_QUEUE,
            start_to_close_timeout=_THUMBNAIL_TIMEOUT,
            schedule_to_close_timeout=THUMBNAIL_SCHEDULE_TO_CLOSE,
            retry_policy=_THUMBNAIL_RETRY,
        )

        await wf.execute_activity(
            finalize_observation_thumbnail_activity,
            FinalizeObservationThumbnailInputs(
                team_id=inputs.team_id,
                observation_id=inputs.observation_id,
                media_asset_id=prepared.media_asset_id,
                video_start_ms=prepared.video_start_ms,
                rec_start_ms=prepared.rec_start_ms,
                result=ExtractThumbnailActivityOutput.model_validate(raw_result),
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            schedule_to_close_timeout=STATE_ACTIVITY_SCHEDULE_TO_CLOSE,
            retry_policy=STATE_ACTIVITY_RETRY,
        )
