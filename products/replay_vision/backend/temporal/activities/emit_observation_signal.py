import structlog
from asgiref.sync import async_to_sync
from temporalio import activity

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import VISION_SIGNALS_SOURCE_PRODUCT, VISION_SIGNALS_SOURCE_TYPE
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scanners.base import MIN_SIGNAL_CONFIDENCE
from products.replay_vision.backend.temporal.types import EmitObservationSignalInputs, ScannerSnapshot
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

# Findings accumulate into a report across sessions; promotion (total_weight >= 1.0) needs corroboration.
SIGNAL_WEIGHT = 0.5


@activity.defn
@track_activity()
def emit_observation_signal_activity(inputs: EmitObservationSignalInputs) -> int:
    """Emit the observation's side-mission finding as a PostHog Signal; fails soft, returns the emitted count."""
    if inputs.signal.confidence < MIN_SIGNAL_CONFIDENCE:
        return 0
    try:
        observation = (
            ReplayObservation.objects.filter(pk=inputs.observation_id, team_id=inputs.team_id)
            .select_related("team")
            .first()
        )
        if observation is None:
            return 0
        snapshot = ScannerSnapshot.load_for(inputs.observation_id, observation.scanner_snapshot)
        # The scanner's `emits_signals` flag is the per-source authorization — there's no separate
        # SignalSourceConfig to consult (the facade allows replay_vision/scanner_finding unconditionally).
        if not snapshot.emits_signals:
            return 0
        # `scanner_name`/`scanner_type` come from the frozen snapshot (what actually ran);
        # `scanner_id`/`session_id` are immutable on the row.
        async_to_sync(emit_signal)(
            team=observation.team,
            source_product=VISION_SIGNALS_SOURCE_PRODUCT,
            source_type=VISION_SIGNALS_SOURCE_TYPE,
            source_id=f"observation:{observation.id}",
            description=inputs.signal.description,
            weight=SIGNAL_WEIGHT,
            extra={
                "scanner_id": str(observation.scanner_id),
                "scanner_name": snapshot.name,
                "scanner_type": snapshot.scanner_type.value,
                "observation_id": str(observation.id),
                "session_id": observation.session_id,
                "confidence": inputs.signal.confidence,
            },
        )
        return 1
    except Exception:
        # Signals are advisory — never fail the observation over emission.
        logger.exception("replay_vision.signal_emission_failed", observation_id=str(inputs.observation_id))
        return 0
