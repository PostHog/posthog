"""Upload the rasterized session MP4 to Gemini and wait for it to be ACTIVE, unless the scan sends it inline."""

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

from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.temporal.common.heartbeat import Heartbeater

from products.exports.backend.models.exported_asset import ExportedAsset
from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import ConsentWithdrawnError, FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.gemini import (
    classify_gemini_error,
    classify_gemini_file_error,
    describe_gemini_error,
    describe_gemini_file_error,
    gemini_api_key,
)
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.tracking import track_uploaded_file
from products.replay_vision.backend.temporal.types import UploadedVideo, UploadVideoToGeminiInputs
from products.replay_vision.backend.temporal.video_asset import MAX_INLINE_VIDEO_BYTES, read_asset_video_bytes

logger = structlog.get_logger(__name__)

# Activity timeout is 10 minutes; this leaves buffer for the rest of the body.
_MAX_PROCESSING_WAIT_SECONDS = 300


@activity.defn(name="replay_vision_upload_video_to_gemini_activity")
@track_activity()
async def upload_video_to_gemini_activity(inputs: UploadVideoToGeminiInputs) -> UploadedVideo:
    """Read the asset's MP4 bytes, upload to Gemini, poll until ACTIVE, return the file reference."""
    # Background heartbeats let Temporal detect a dead worker in ~2 min instead of the full 10-min timeout.
    async with Heartbeater(factor=4):
        try:
            return await _upload_video(inputs)
        except Exception as e:
            kind = classify_gemini_error(e)
            if kind is None:
                raise
            # The raw error body can quote request content, so it stays out of both the user-visible
            # error_reason and the logs; code + status carry the diagnostic signal.
            logger.warning(
                "replay_vision.upload_video_to_gemini.provider_error",
                kind=kind.value,
                error_type=type(e).__name__,
                code=getattr(e, "code", None),
                status=getattr(e, "status", None),
            )
            raise ScannerFailureError(describe_gemini_error(e), kind=kind) from e


async def _upload_video(inputs: UploadVideoToGeminiInputs) -> UploadedVideo:
    workflow_id = activity.info().workflow_id
    if workflow_id is None:
        raise ScannerFailureError("upload_video_to_gemini_activity has no workflow_id", kind=FailureKind.INTERNAL_ERROR)
    asset = await ExportedAsset.objects.aget(id=inputs.asset_id)

    # Re-check consent at the egress boundary, keyed off the team that owns the bytes: an admin may have
    # revoked it after the observation was created but before these bytes leave for Gemini. Fail closed so
    # a withdrawn org can't have recordings processed.
    if not await sync_to_async(is_ai_data_processing_approved)(asset.team_id):
        raise ConsentWithdrawnError("AI data processing consent was withdrawn before this recording could be analyzed")

    video_bytes = await read_asset_video_bytes(asset)
    # The gateway serves no Files API, so the scan sends the bytes inline. A video over the inline bound uploads
    # directly, because the gateway rejects every turn that carries it.
    if resolve_ai_gateway_config() is not None:
        if len(video_bytes) <= MAX_INLINE_VIDEO_BYTES:
            return UploadedVideo(file_uri="", mime_type=asset.export_format, gemini_file_name="", inline_video=True)
        logger.warning(
            "replay_vision.upload_video_to_gemini.inline_too_large_uploading_directly",
            size_bytes=len(video_bytes),
            limit_bytes=MAX_INLINE_VIDEO_BYTES,
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
        file_error = uploaded_file.error
        kind = classify_gemini_file_error(file_error)
        # The provider's own message can quote request content, so only its code reaches the log and the user.
        logger.warning(
            "replay_vision.upload_video_to_gemini.file_not_active",
            state=final_state,
            kind=kind.value,
            error_code=file_error.code if file_error else None,
            gemini_file_name=gemini_file_name,
        )
        raise ScannerFailureError(describe_gemini_file_error(file_error), kind=kind)
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
        try:
            return raw_client.files.upload(
                file=tmp_file.name,
                config=types.UploadFileConfig(mime_type=mime_type, display_name=workflow_id),
            )
        except (KeyError, ValueError, TypeError) as e:
            # google-genai does not check the finalize response's HTTP status; a failed upload surfaces as one of these.
            raise ScannerFailureError(
                "The AI provider did not finish the video upload", kind=FailureKind.PROVIDER_TRANSIENT
            ) from e
