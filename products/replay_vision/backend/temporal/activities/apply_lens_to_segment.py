from uuid import UUID

from django.conf import settings

import temporalio.activity
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.temporal.lenses import get_lens_impl
from products.replay_vision.backend.temporal.types import SegmentLensOutput, UploadedVideo, VisionVideoSegmentSpec


@temporalio.activity.defn
async def apply_lens_to_segment_activity(
    lens_id: UUID,
    uploaded_video: UploadedVideo,
    segment: VisionVideoSegmentSpec,
    trace_id: str,
) -> SegmentLensOutput:
    @database_sync_to_async
    def _load_lens() -> ReplayLens:
        return ReplayLens.objects.get(id=lens_id)

    lens = await _load_lens()
    impl = get_lens_impl(lens.lens_type)
    prompt = impl.system_prompt(lens.lens_config)

    client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
    response = await client.models.generate_content(
        model=lens.model,
        contents=[
            types.Part(
                file_data=types.FileData(file_uri=uploaded_video.file_uri, mime_type=uploaded_video.mime_type),
                video_metadata=types.VideoMetadata(
                    start_offset=f"{round(segment.recording_start_time, 2)}s",
                    end_offset=f"{round(segment.recording_end_time, 2)}s",
                ),
            ),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=impl.SegmentOutput,
        ),
        posthog_trace_id=trace_id,
        posthog_groups={"project": str(lens.team_id)},
    )

    raw = (response.text or "").strip()
    try:
        validated = impl.SegmentOutput.model_validate_json(raw)
    except Exception as e:
        msg = f"Lens {lens.lens_type} segment {segment.segment_index} returned invalid output: {e}"
        temporalio.activity.logger.exception(msg, extra={"lens_id": str(lens_id), "raw": raw})
        raise ApplicationError(msg, non_retryable=True)

    return SegmentLensOutput(segment_index=segment.segment_index, output_json=validated.model_dump_json())
