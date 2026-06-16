"""Upload the rasterized session MP4 to Gemini and wait for it to be ACTIVE."""

import time
import asyncio
import tempfile
from datetime import UTC, datetime

import structlog
from asgiref.sync import sync_to_async
from google.genai import (
    Client as RawGenAIClient,
    types,
)
from temporalio import activity

from posthog.storage import object_storage

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.tracking import track_uploaded_file
from products.replay_vision.backend.temporal.types import UploadedVideo, UploadVideoToGeminiInputs

logger = structlog.get_logger(__name__)

# Activity timeout is 10 minutes; this leaves buffer for the rest of the body.
_MAX_PROCESSING_WAIT_SECONDS = 300


@activity.defn(name="replay_vision_upload_video_to_gemini_activity")
@track_activity()
async def upload_video_to_gemini_activity(inputs: UploadVideoToGeminiInputs) -> UploadedVideo:
    """Read the asset's MP4 bytes, upload to Gemini, poll until ACTIVE, return the file reference."""
    workflow_id = activity.info().workflow_id
    if workflow_id is None:
        raise ScannerFailureError("upload_video_to_gemini_activity has no workflow_id", kind=FailureKind.INTERNAL_ERROR)
    asset = await ExportedAsset.objects.aget(id=inputs.asset_id)

    video_bytes: bytes | None
    if asset.content:
        video_bytes = bytes(asset.content)
    elif asset.content_location:
        video_bytes = await sync_to_async(object_storage.read_bytes, thread_sensitive=False)(asset.content_location)
    else:
        raise ScannerFailureError(
            f"ExportedAsset {inputs.asset_id} has neither content nor content_location",
            kind=FailureKind.INTERNAL_ERROR,
        )
    if not video_bytes:
        raise ScannerFailureError(
            f"ExportedAsset {inputs.asset_id} produced empty video bytes", kind=FailureKind.INTERNAL_ERROR
        )

    raw_client = RawGenAIClient(api_key=gemini_api_key())
    # `tmp_file.write` / `flush` are blocking disk I/O; offload the whole tempfile+upload block off the event loop.
    uploaded_file = await asyncio.to_thread(
        _write_and_upload, raw_client, video_bytes, asset.export_format, workflow_id
    )

    if uploaded_file.name is None:
        # Non-retryable: a retry would re-upload before the cleanup sweep can reap the unnamed file Gemini may have created.
        raise ScannerFailureError(
            "Gemini upload returned a file without a name",
            kind=FailureKind.INTERNAL_ERROR,
        )
    gemini_file_name = uploaded_file.name

    # Track BEFORE the ACTIVE-wait so a polling timeout still leaves the file visible to the cleanup sweep.
    try:
        await track_uploaded_file(gemini_file_name, workflow_id, datetime.now(UTC))
    except Exception:
        logger.exception("replay_vision.upload_video_to_gemini.track_failed_rolling_back")
        try:
            await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=gemini_file_name)
        except Exception:
            logger.exception("replay_vision.upload_video_to_gemini.rollback_delete_failed")
        raise

    wait_start = time.time()
    while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
        elapsed = time.time() - wait_start
        if elapsed >= _MAX_PROCESSING_WAIT_SECONDS:
            raise ScannerFailureError(
                f"Gemini file {gemini_file_name} stuck in PROCESSING after {elapsed:.1f}s; left for the cleanup sweep",
                kind=FailureKind.PROVIDER_TRANSIENT,
            )
        await asyncio.sleep(0.5)
        uploaded_file = await sync_to_async(raw_client.files.get, thread_sensitive=False)(name=gemini_file_name)

    final_state = uploaded_file.state.name if uploaded_file.state else None
    if final_state != "ACTIVE":
        raise ScannerFailureError(
            f"Gemini file {gemini_file_name} reached non-ACTIVE state {final_state!r}",
            kind=FailureKind.PROVIDER_REJECTED,
        )
    if not uploaded_file.uri:
        raise ScannerFailureError(
            f"Gemini file {gemini_file_name} reached ACTIVE but has no URI",
            kind=FailureKind.PROVIDER_TRANSIENT,
        )

    return UploadedVideo(
        file_uri=uploaded_file.uri,
        mime_type=uploaded_file.mime_type or asset.export_format,
        gemini_file_name=gemini_file_name,
    )


def _write_and_upload(raw_client: RawGenAIClient, video_bytes: bytes, mime_type: str, workflow_id: str) -> types.File:
    with tempfile.NamedTemporaryFile() as tmp_file:
        tmp_file.write(video_bytes)
        tmp_file.flush()
        return raw_client.files.upload(
            file=tmp_file.name,
            config=types.UploadFileConfig(mime_type=mime_type, display_name=workflow_id),
        )
