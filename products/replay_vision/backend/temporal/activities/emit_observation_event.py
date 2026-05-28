"""Emit the `$recording_observed` event with the scanner output to the customer's events table."""

from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.api.capture import capture_internal
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.types import EmitObservationEventInputs, ScannerSnapshot

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$recording_observed"
_EVENT_SOURCE = "replay_vision"


@activity.defn
async def emit_observation_event_activity(inputs: EmitObservationEventInputs) -> None:
    """Capture the `$recording_observed` event into the customer's events table; dedup-keyed by observation_id."""
    await database_sync_to_async(_emit_event, thread_sensitive=False)(inputs)


def _emit_event(inputs: EmitObservationEventInputs) -> None:
    observation = ReplayObservation.objects.select_related("team").filter(pk=inputs.observation_id).first()
    if observation is None:
        raise ScannerFailureError(
            f"ReplayObservation {inputs.observation_id} not found", kind=FailureKind.INTERNAL_ERROR
        )

    try:
        team: Team = observation.team
    except Team.DoesNotExist:
        raise ScannerFailureError(
            f"Team for observation {inputs.observation_id} not found", kind=FailureKind.INTERNAL_ERROR
        )

    snapshot = ScannerSnapshot.load_for(inputs.observation_id, observation.scanner_snapshot)
    properties: dict = {
        # Deterministic id so a worker crash mid-flush doesn't produce a duplicate event row.
        "$insert_id": str(observation.id),
        "scanner_id": str(observation.scanner_id),
        "scanner_name": snapshot.name,
        "scanner_type": snapshot.scanner_type.value,
        "scanner_version": snapshot.scanner_version,
        "session_id": observation.session_id,
        "triggered_by": str(observation.triggered_by),
        "triggered_by_user_id": observation.triggered_by_user_id,
        "model_used": snapshot.model.value,
        "provider_used": snapshot.provider.value,
        "emits_signals": snapshot.emits_signals,
        # Flatten scanner output so HogQL can query individual fields without a JSON extract.
        **inputs.model_output.to_event_properties(),
    }
    distinct_id = (
        str(observation.triggered_by_user_id)
        if observation.triggered_by_user_id is not None and observation.triggered_by == ObservationTrigger.ON_DEMAND
        else replay_vision_distinct_id(observation.team_id)
    )

    response = capture_internal(
        token=team.api_token,
        event_name=_EVENT_NAME,
        event_source=_EVENT_SOURCE,
        distinct_id=distinct_id,
        timestamp=datetime.now(UTC),
        properties=properties,
        process_person_profile=False,
    )
    response.raise_for_status()
