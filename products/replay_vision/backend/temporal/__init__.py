from collections.abc import Callable
from typing import Any

from products.replay_vision.backend.temporal.activities import (
    advance_scanner_watermark_activity,
    call_scanner_provider_activity,
    cleanup_gemini_file_activity,
    create_observation_activity,
    delete_scanner_schedule_activity,
    embed_summarizer_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    ensure_session_asset_activity,
    fetch_session_events_activity,
    find_scanner_candidates_activity,
    list_enabled_scanners_activity,
    list_scanner_schedules_activity,
    mark_observation_failed_activity,
    mark_observation_ineligible_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
    upload_video_to_gemini_activity,
    upsert_scanner_schedule_activity,
)
from products.replay_vision.backend.temporal.reconciler import ReconcileScannerSchedulesWorkflow
from products.replay_vision.backend.temporal.sweep_workflow import SweepScannerWorkflow
from products.replay_vision.backend.temporal.workflow import ApplyScannerWorkflow

WORKFLOWS = [ApplyScannerWorkflow, ReconcileScannerSchedulesWorkflow, SweepScannerWorkflow]
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
    embed_summarizer_observation_activity,
    emit_classifier_tags_activity,
    emit_observation_event_activity,
    cleanup_gemini_file_activity,
    find_scanner_candidates_activity,
    advance_scanner_watermark_activity,
    list_enabled_scanners_activity,
    list_scanner_schedules_activity,
    upsert_scanner_schedule_activity,
    delete_scanner_schedule_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ApplyScannerWorkflow",
    "ReconcileScannerSchedulesWorkflow",
    "SweepScannerWorkflow",
    "advance_scanner_watermark_activity",
    "call_scanner_provider_activity",
    "cleanup_gemini_file_activity",
    "create_observation_activity",
    "delete_scanner_schedule_activity",
    "embed_summarizer_observation_activity",
    "emit_classifier_tags_activity",
    "emit_observation_event_activity",
    "ensure_session_asset_activity",
    "fetch_session_events_activity",
    "find_scanner_candidates_activity",
    "list_enabled_scanners_activity",
    "list_scanner_schedules_activity",
    "mark_observation_failed_activity",
    "mark_observation_ineligible_activity",
    "mark_observation_running_activity",
    "mark_observation_succeeded_activity",
    "upload_video_to_gemini_activity",
    "upsert_scanner_schedule_activity",
]
