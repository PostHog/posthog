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
from products.replay_vision.backend.temporal.workflow import ApplyLensWorkflow

REPLAY_VISION_WORKFLOWS = [ApplyLensWorkflow]

REPLAY_VISION_ACTIVITIES = [
    create_observation_activity,
    mark_observation_failed_activity,
    prep_session_video_asset_activity,
    upload_video_to_gemini_activity,
    apply_lens_to_segment_activity,
    consolidate_lens_segments_activity,
    cleanup_gemini_file_activity,
    emit_lens_event_and_mark_succeeded_activity,
]
