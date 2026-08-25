from temporalio import activity

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import AdvanceScannerWatermarkInputs


@activity.defn
@track_activity()
def advance_scanner_watermark_activity(inputs: AdvanceScannerWatermarkInputs) -> None:
    updates: dict[str, object] = {
        "last_swept_at": inputs.new_last_swept_at,
        "last_seen_session_id": inputs.new_last_seen_session_id,
    }
    if inputs.new_last_deep_swept_at is not None:
        updates["deep_swept_through"] = inputs.new_last_deep_swept_at
        updates["deep_seen_session_id"] = inputs.new_last_deep_seen_session_id
    updated = ReplayScanner.objects.filter(pk=inputs.scanner_id).update(**updates)
    if updated == 0:
        activity.logger.info(
            "advance_scanner_watermark: scanner no longer exists",
            extra={"scanner_id": str(inputs.scanner_id)},
        )
