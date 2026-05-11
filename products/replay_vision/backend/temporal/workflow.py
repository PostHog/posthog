import asyncio
from datetime import timedelta
from typing import Any

from django.conf import settings

import structlog
import temporalio
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs

from products.replay_vision.backend.temporal.activities.apply_lens_to_segment import apply_lens_to_segment_activity
from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file_activity
from products.replay_vision.backend.temporal.activities.consolidate_lens_segments import (
    consolidate_lens_segments_activity,
)
from products.replay_vision.backend.temporal.activities.emit_lens_event import (
    emit_lens_event_and_mark_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.observation_state import (
    create_observation_activity,
    mark_observation_failed_activity,
)
from products.replay_vision.backend.temporal.activities.prep_session_video_asset import (
    prep_session_video_asset_activity,
)
from products.replay_vision.backend.temporal.activities.upload_video_to_gemini import upload_video_to_gemini_activity
from products.replay_vision.backend.temporal.constants import MIN_SEGMENT_DURATION_S, VISION_VIDEO_CHUNK_DURATION_S
from products.replay_vision.backend.temporal.types import ApplyLensInputs, SegmentLensOutput, VisionVideoSegmentSpec

logger = structlog.get_logger(__name__)


def _calculate_segment_specs(
    video_duration: float,
    chunk_duration: float,
    inactivity_periods: list[dict[str, Any]] | None,
) -> list[VisionVideoSegmentSpec]:
    """Slice active periods into chunks of at most `chunk_duration` seconds.

    Inactive periods are skipped entirely. If no inactivity data is available, falls back to
    chunking the whole video. Inactivity periods are passed as plain dicts (the
    `ReplayInactivityPeriod.model_dump()` shape) so this function stays free of schema imports.
    """
    segments: list[VisionVideoSegmentSpec] = []
    segment_index = 0

    if not inactivity_periods:
        cursor = 0.0
        while cursor < video_duration:
            end = min(cursor + chunk_duration, video_duration)
            if end - cursor >= MIN_SEGMENT_DURATION_S:
                segments.append(
                    VisionVideoSegmentSpec(
                        segment_index=segment_index, recording_start_time=cursor, recording_end_time=end
                    )
                )
                segment_index += 1
            cursor = end
        return segments

    for period in inactivity_periods:
        if not period.get("active"):
            continue
        period_start = period.get("recording_ts_from_s")
        if period_start is None:
            continue
        period_end = period.get("recording_ts_to_s") or video_duration
        cursor = float(period_start)
        recording_end = float(period_end)
        while cursor < recording_end:
            end = min(cursor + chunk_duration, recording_end)
            if 0 < recording_end - end < chunk_duration:
                end = recording_end
            if end - cursor >= MIN_SEGMENT_DURATION_S:
                segments.append(
                    VisionVideoSegmentSpec(
                        segment_index=segment_index, recording_start_time=cursor, recording_end_time=end
                    )
                )
                segment_index += 1
            cursor = end
    return segments


@temporalio.workflow.defn(name="apply-lens")
class ApplyLensWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self, inputs: ApplyLensInputs) -> None:
        retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
        workflow_id = temporalio.workflow.info().workflow_id

        observation_id = await temporalio.workflow.execute_activity(
            create_observation_activity,
            args=(inputs.lens_id, inputs.session_id, inputs.triggered_by, inputs.user_id, workflow_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry_policy,
        )

        try:
            export_result = await temporalio.workflow.execute_activity(
                prep_session_video_asset_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=retry_policy,
            )
            asset_id = export_result.asset_id

            rasterize_workflow_id = f"replay-vision-rasterize_{inputs.team_id}_{inputs.session_id}_{observation_id}"
            await temporalio.workflow.execute_child_workflow(
                "rasterize-recording",
                RasterizeRecordingInputs(exported_asset_id=asset_id),
                id=rasterize_workflow_id,
                task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
                retry_policy=retry_policy,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=timedelta(minutes=30),
                search_attributes=TypedSearchAttributes(
                    search_attributes=[
                        SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id),
                        SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=inputs.session_id),
                    ]
                ),
            )

            upload_result = await temporalio.workflow.execute_activity(
                upload_video_to_gemini_activity,
                args=(inputs, asset_id),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
            uploaded_video = upload_result.uploaded_video
            inactivity_periods = upload_result.inactivity_periods

            segment_specs = _calculate_segment_specs(
                video_duration=uploaded_video.duration,
                chunk_duration=VISION_VIDEO_CHUNK_DURATION_S,
                inactivity_periods=inactivity_periods,
            )
            if not segment_specs:
                raise ApplicationError("No analyzable segments produced for session", non_retryable=True)

            trace_id = str(observation_id)

            try:
                semaphore = asyncio.Semaphore(20)

                async def _apply_with_semaphore(segment_spec: VisionVideoSegmentSpec) -> SegmentLensOutput:
                    async with semaphore:
                        return await temporalio.workflow.execute_activity(
                            apply_lens_to_segment_activity,
                            args=(inputs.lens_id, uploaded_video, segment_spec, trace_id),
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=retry_policy,
                        )

                segment_outputs = await asyncio.gather(*(_apply_with_semaphore(spec) for spec in segment_specs))

                final = await temporalio.workflow.execute_activity(
                    consolidate_lens_segments_activity,
                    args=(inputs.lens_id, segment_outputs),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy,
                )
            finally:
                await temporalio.workflow.execute_activity(
                    cleanup_gemini_file_activity,
                    args=(uploaded_video.gemini_file_name, inputs.session_id),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

            await temporalio.workflow.execute_activity(
                emit_lens_event_and_mark_succeeded_activity,
                args=(observation_id, inputs.lens_id, inputs.session_id, final),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=retry_policy,
            )
        except Exception as e:
            await temporalio.workflow.execute_activity(
                mark_observation_failed_activity,
                args=(observation_id, str(e)[:1000]),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            raise
