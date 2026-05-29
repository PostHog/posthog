"""Best-effort cleanup of a Gemini file uploaded by `upload_video_to_gemini_activity`."""

from django.conf import settings

import structlog
from asgiref.sync import sync_to_async
from google.genai import Client as RawGenAIClient
from temporalio import activity

from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import untrack_uploaded_file

from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import CleanupGeminiFileInputs

logger = structlog.get_logger(__name__)


@activity.defn(name="replay_vision_cleanup_gemini_file_activity")
@track_activity()
async def cleanup_gemini_file_activity(inputs: CleanupGeminiFileInputs) -> None:
    """Best-effort delete of the uploaded Gemini file; the cleanup sweep retries on failure via the tracking key."""
    try:
        raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
        await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=inputs.gemini_file_name)
    except Exception:
        logger.exception("replay_vision.cleanup_gemini_file.delete_failed", gemini_file_name=inputs.gemini_file_name)
        return

    await untrack_uploaded_file(inputs.gemini_file_name)
