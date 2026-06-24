"""Best-effort cleanup of a Gemini file uploaded by `upload_video_to_gemini_activity`."""

import structlog
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient
from temporalio import activity

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.gemini import gemini_api_key
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.tracking import (
    is_gemini_file_gone,
    untrack_uploaded_file,
)
from products.replay_vision.backend.temporal.types import CleanupGeminiFileInputs

logger = structlog.get_logger(__name__)


@activity.defn(name="replay_vision_cleanup_gemini_file_activity")
@track_activity()
async def cleanup_gemini_file_activity(inputs: CleanupGeminiFileInputs) -> None:
    """Best-effort delete of the uploaded Gemini file; the cleanup sweep retries on transient failure via the tracking key."""
    try:
        raw_client = RawGenAIClient(api_key=gemini_api_key())
        await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=inputs.gemini_file_name)
    except Exception as e:
        if not is_gemini_file_gone(e):
            logger.exception(
                "replay_vision.cleanup_gemini_file.delete_failed", gemini_file_name=inputs.gemini_file_name
            )
            return
        # File already gone — untrack so the sweep doesn't retry a doomed delete forever.
        logger.info("replay_vision.cleanup_gemini_file.already_gone", gemini_file_name=inputs.gemini_file_name)

    await untrack_uploaded_file(inputs.gemini_file_name)
