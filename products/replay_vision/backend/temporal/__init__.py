from collections.abc import Callable
from typing import Any

from products.replay_vision.backend.temporal.activities import (
    call_scanner_provider_activity,
    cleanup_gemini_file_activity,
    create_observation_activity,
    embed_indexer_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
    upload_video_to_gemini_activity,
)
from products.replay_vision.backend.temporal.workflow import ApplyScannerWorkflow

WORKFLOWS = [ApplyScannerWorkflow]
ACTIVITIES: list[Callable[..., Any]] = [
    create_observation_activity,
    mark_observation_running_activity,
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_succeeded_activity,
    fetch_session_events_activity,
    ensure_session_asset_activity,
    upload_video_to_gemini_activity,
    call_scanner_provider_activity,
    embed_indexer_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    cleanup_gemini_file_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ApplyScannerWorkflow",
    "call_scanner_provider_activity",
    "cleanup_gemini_file_activity",
    "create_observation_activity",
    "embed_indexer_observation_activity",
    "emit_classifier_tags_activity",
    "emit_observation_event_activity",
    "ensure_session_asset_activity",
    "fetch_session_events_activity",
    "mark_observation_failed_activity",
    "mark_observation_ineligible_activity",
    "mark_observation_running_activity",
    "mark_observation_succeeded_activity",
    "upload_video_to_gemini_activity",
]
