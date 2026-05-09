import math
import time
import asyncio
import tempfile
from datetime import UTC, datetime
from io import BytesIO

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from google.genai import (
    Client as RawGenAIClient,
    types,
)
from pymediainfo import MediaInfo

from posthog.models.exported_asset import ExportedAsset
from posthog.storage import object_storage
from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import track_uploaded_file

from products.replay_vision.backend.temporal.constants import FULL_VIDEO_EXPORT_FORMAT
from products.replay_vision.backend.temporal.types import ApplyLensInputs, UploadedVideo, UploadVideoToGeminiOutput

logger = structlog.get_logger(__name__)


def _get_video_duration_s(video_bytes: bytes) -> int:
    media_info = MediaInfo.parse(BytesIO(video_bytes))
    for track in media_info.tracks:
        if track.track_type == "General":
            if track.duration is None:
                raise ValueError("Video General track has no duration")
            return int(math.ceil(track.duration / 1000.0))
    raise ValueError("No General track found in video to extract duration from")


MAX_PROCESSING_WAIT_SECONDS = 300


@temporalio.activity.defn
async def upload_video_to_gemini_activity(inputs: ApplyLensInputs, asset_id: int) -> UploadVideoToGeminiOutput:
    """Upload the rendered session video to Gemini Files API and return a reusable file_uri.

    Tracking happens before the ACTIVE-wait so a polling timeout still leaves the file visible
    to `gemini_cleanup_sweep`. On track failure the just-uploaded file is deleted inline.
    """
    workflow_id = temporalio.activity.info().workflow_id
    if workflow_id is None:
        raise RuntimeError("activity has no workflow_id")
    asset = await ExportedAsset.objects.aget(id=asset_id)

    video_bytes: bytes | None = None
    if asset.content:
        video_bytes = bytes(asset.content)
    elif asset.content_location:
        video_bytes = await sync_to_async(object_storage.read_bytes, thread_sensitive=False)(asset.content_location)
    else:
        raise ValueError(f"Content location is unset for asset {asset_id} for session {inputs.session_id}")
    if not video_bytes:
        raise ValueError(f"No video content found for asset {asset_id} for session {inputs.session_id}")

    duration = await sync_to_async(_get_video_duration_s, thread_sensitive=False)(video_bytes)
    raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)

    with tempfile.NamedTemporaryFile() as tmp_file:
        tmp_file.write(video_bytes)
        tmp_file.flush()
        uploaded_file = await sync_to_async(raw_client.files.upload, thread_sensitive=False)(
            file=tmp_file.name,
            config=types.UploadFileConfig(mime_type=asset.export_format, display_name=workflow_id),
        )

    try:
        if uploaded_file.name is None:
            raise RuntimeError("Uploaded file has no name")
        await track_uploaded_file(uploaded_file.name, workflow_id, datetime.now(UTC))
    except Exception:
        if uploaded_file.name is not None:
            try:
                await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=uploaded_file.name)
            except Exception:
                logger.exception("upload_video_to_gemini.rollback_delete_failed", session_id=inputs.session_id)
        raise

    gemini_file_name = uploaded_file.name
    assert gemini_file_name is not None  # narrowing for mypy

    wait_start = time.time()
    while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
        elapsed = time.time() - wait_start
        if elapsed >= MAX_PROCESSING_WAIT_SECONDS:
            raise RuntimeError(
                f"Gemini file processing timed out after {elapsed:.1f}s. State: {uploaded_file.state.name}"
            )
        await asyncio.sleep(0.5)
        uploaded_file = await sync_to_async(raw_client.files.get, thread_sensitive=False)(name=gemini_file_name)

    final_state = uploaded_file.state.name if uploaded_file.state else None
    if final_state != "ACTIVE":
        raise RuntimeError(f"Gemini file processing failed. State: {final_state}")
    if not uploaded_file.uri:
        raise RuntimeError("Uploaded file has no URI")

    uploaded_video = UploadedVideo(
        file_uri=uploaded_file.uri,
        gemini_file_name=gemini_file_name,
        mime_type=uploaded_file.mime_type or FULL_VIDEO_EXPORT_FORMAT,
        duration=duration,
    )
    inactivity_periods = asset.export_context.get("inactivity_periods") if asset.export_context else None
    return UploadVideoToGeminiOutput(uploaded_video=uploaded_video, inactivity_periods=inactivity_periods)
