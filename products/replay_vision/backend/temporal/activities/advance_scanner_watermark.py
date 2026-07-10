from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.sweep_types import AdvanceScannerWatermarkInputs


@activity.defn
@close_db_connections
@track_activity()
def advance_scanner_watermark_activity(inputs: AdvanceScannerWatermarkInputs) -> None:
    updated = ReplayScanner.objects.filter(pk=inputs.scanner_id).update(
        last_swept_at=inputs.new_last_swept_at,
        last_seen_session_id=inputs.new_last_seen_session_id,
    )
    if updated == 0:
        activity.logger.info(
            "advance_scanner_watermark: scanner no longer exists",
            extra={"scanner_id": str(inputs.scanner_id)},
        )
