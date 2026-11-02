"""Best-effort cleanup of a Gemini file uploaded by `upload_video_to_gemini_activity`."""

from temporalio import activity

from products.replay_vision.backend.gemini_client import gemini_files_client
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.gemini_cleanup_sweep.tracking import delete_and_untrack
from products.replay_vision.backend.temporal.types import CleanupGeminiFileInputs


@activity.defn(name="replay_vision_cleanup_gemini_file_activity")
@track_activity()
async def cleanup_gemini_file_activity(inputs: CleanupGeminiFileInputs) -> None:
    """Best-effort delete of the uploaded Gemini file; the cleanup sweep retries on transient failure via the tracking key."""
    raw_client = gemini_files_client()
    await delete_and_untrack(raw_client, inputs.gemini_file_name, log_source="replay_vision.cleanup_gemini_file")
