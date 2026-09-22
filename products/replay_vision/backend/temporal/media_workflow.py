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
    from products.replay_vision.backend.temporal.media_types import (
        ExtractThumbnailActivityOutput,
        FinalizeObservationThumbnailInputs,
        ObservationMediaInputs,
        PrepareObservationThumbnailOutput,
    )

_THUMBNAIL_TIMEOUT = dt.timedelta(minutes=5)
_STATE_RETRY = common.RetryPolicy(maximum_attempts=3)


@wf.defn(name="replay-vision-media")
class ObservationMediaWorkflow(PostHogWorkflow):
    """Render the media that illustrates one succeeded observation. Today that is a single thumbnail."""

    inputs_cls = ObservationMediaInputs

    @wf.run
    async def run(self, inputs: ObservationMediaInputs) -> None:
        prepared: PrepareObservationThumbnailOutput = await wf.execute_activity(
            prepare_observation_thumbnail_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_RETRY,
        )

        raw_result = await wf.execute_activity(
            "extract-thumbnail",
            prepared.activity_input.model_dump(exclude_none=True),
            task_queue=settings.RASTERIZATION_MEDIA_TASK_QUEUE,
            start_to_close_timeout=_THUMBNAIL_TIMEOUT,
            retry_policy=common.RetryPolicy(maximum_attempts=2),
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
            retry_policy=_STATE_RETRY,
        )
