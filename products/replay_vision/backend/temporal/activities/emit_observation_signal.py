from typing import Any
from uuid import UUID

import structlog
from asgiref.sync import async_to_sync
from temporalio import activity

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.constants import VISION_SIGNALS_SOURCE_PRODUCT, VISION_SIGNALS_SOURCE_TYPE
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.scanners.base import MIN_SIGNAL_CONFIDENCE
from products.replay_vision.backend.temporal.state import load_scanner_llm_inputs
from products.replay_vision.backend.temporal.types import EmitObservationSignalInputs, ScannerLlmInputs, ScannerSnapshot
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

# Findings accumulate into a report across sessions; promotion (total_weight >= 1.0) needs corroboration.
SIGNAL_WEIGHT = 0.5


def _load_llm_inputs(observation_id: UUID) -> ScannerLlmInputs | None:
    """Read the per-session inputs the scan already stashed in Redis; None if absent (TTL lapsed)."""
    return async_to_sync(load_scanner_llm_inputs)(str(observation_id))


@activity.defn
@track_activity()
def emit_observation_signal_activity(inputs: EmitObservationSignalInputs) -> int:
    """Emit the observation's side-mission findings as PostHog Signals; fails soft, returns the emitted count."""
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
        # Observation-wide metadata, shared by every finding. `scanner_name`/`scanner_type` come from the
        # frozen snapshot (what actually ran); `scanner_id`/`session_id` are immutable on the row. The
        # `recording_*` fields are the snapshot time bounds — `recording_start_time` is the REC_T=0 anchor,
        # so `recording_start_time + start_time` gives a finding's absolute instant. (Recording can begin
        # well after the session does, depending on customer config, so these are the *recording* bounds.)
        base_extra: dict[str, Any] = {
            "scanner_id": str(observation.scanner_id),
            "scanner_name": snapshot.name,
            "scanner_type": snapshot.scanner_type.value,
            "observation_id": str(observation.id),
            "session_id": observation.session_id,
            "exported_asset_id": inputs.exported_asset_id,
        }
        # Reuse the session metadata already fetched at the start of the scan (stashed in Redis as
        # `ScannerLlmInputs`) rather than re-querying ClickHouse here. Enrichment is best-effort: a Redis
        # error here must degrade to no-enrichment, not drop every signal (the findings need no lookup).
        try:
            llm_inputs = _load_llm_inputs(inputs.observation_id)
        except Exception:
            logger.exception("replay_vision.signal_enrichment_failed", observation_id=str(inputs.observation_id))
            llm_inputs = None
        if llm_inputs is not None:
            meta = llm_inputs.metadata
            base_extra["distinct_id"] = llm_inputs.distinct_id
            base_extra["recording_start_time"] = meta.start_time.isoformat()
            base_extra["recording_end_time"] = meta.end_time.isoformat()
            base_extra["recording_duration"] = meta.duration_seconds
            base_extra["recording_active_seconds"] = meta.active_seconds

        emitted = 0
        for index, signal in enumerate(inputs.signals):
            if signal.confidence < MIN_SIGNAL_CONFIDENCE:
                continue
            try:
                async_to_sync(emit_signal)(
                    team=observation.team,
                    source_product=VISION_SIGNALS_SOURCE_PRODUCT,
                    source_type=VISION_SIGNALS_SOURCE_TYPE,
                    # Unique per finding so several issues from one observation don't collide on dedup.
                    source_id=f"observation:{observation.id}:{index}",
                    description=signal.description,
                    weight=SIGNAL_WEIGHT,
                    extra={
                        **base_extra,
                        "confidence": signal.confidence,
                        "problem_type": signal.problem_type,
                        "start_time": signal.start_time,
                        "end_time": signal.end_time,
                        "url": signal.url,
                    },
                )
                emitted += 1
            except Exception:
                # One bad finding never blocks the rest; signals are advisory.
                logger.exception(
                    "replay_vision.signal_emission_failed",
                    observation_id=str(inputs.observation_id),
                    finding_index=index,
                )
        return emitted
    except Exception:
        # Never fail the observation over emission.
        logger.exception("replay_vision.signal_emission_failed", observation_id=str(inputs.observation_id))
        return 0
