"""Emit the `$recording_observed` event with the scanner output to the customer's events table."""

from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.api.capture import capture_internal
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError

# Import from `scanners` (which itself imports `types`) before `types` so the types<->scanners package
# cycle resolves scanners-first regardless of who imports this module first.
from products.replay_vision.backend.temporal.scanners.base import BaseScannerOutput
from products.replay_vision.backend.temporal.types import EmitObservationEventInputs, ScannerSnapshot

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$recording_observed"
_EVENT_SOURCE = "replay_vision"


@activity.defn
@track_activity()
async def emit_observation_event_activity(inputs: EmitObservationEventInputs) -> None:
    """Capture the `$recording_observed` event into the customer's events table; dedup-keyed by observation_id."""
    await database_sync_to_async(_emit_event, thread_sensitive=False)(inputs)


def _emit_event(inputs: EmitObservationEventInputs) -> None:
    observation = ReplayObservation.objects.select_related("team").filter(pk=inputs.observation_id).first()
    if observation is None:
        raise ScannerFailureError(
            f"ReplayObservation {inputs.observation_id} not found", kind=FailureKind.INTERNAL_ERROR
        )
    emit_observation_event(observation, inputs.model_output)


def emit_observation_event(observation: ReplayObservation, model_output: BaseScannerOutput) -> None:
    """Capture the `$recording_observed` event for a persisted observation and stamp `event_emitted_at`.

    Shared by the apply workflow (fresh output in hand) and the reconciler's backfill (output reloaded from
    the persisted result). `$insert_id`/`event_uuid` are keyed to the observation id, so a re-emit dedups
    against an earlier partial success rather than producing a duplicate event row.
    """
    try:
        team: Team = observation.team
    except Team.DoesNotExist:
        raise ScannerFailureError(f"Team for observation {observation.id} not found", kind=FailureKind.INTERNAL_ERROR)

    snapshot = ScannerSnapshot.load_for(observation.id, observation.scanner_snapshot)
    # The recorded subject (distinct from the user who triggered the scan), persisted at scan time.
    recording_distinct_id = observation.distinct_id
    recording_subject_email = observation.recording_subject_email
    properties: dict = {
        # Deterministic id so a worker crash mid-flush doesn't produce a duplicate event row.
        "$insert_id": str(observation.id),
        # Owning team/org so observations can be attributed and billed per tenant.
        "team_id": observation.team_id,
        "organization_id": str(team.organization_id),
        "scanner_id": str(observation.scanner_id),
        "scanner_name": snapshot.name,
        "scanner_type": snapshot.scanner_type.value,
        "scanner_version": snapshot.scanner_version,
        "session_id": observation.session_id,
        "recording_distinct_id": recording_distinct_id,
        "recording_subject_email": recording_subject_email,
        "triggered_by": str(observation.triggered_by),
        "triggered_by_user_id": observation.triggered_by_user_id,
        "model_used": snapshot.model,
        "provider_used": snapshot.provider,
        "emits_signals": snapshot.emits_signals,
        # Flatten scanner output so HogQL can query individual fields without a JSON extract.
        **model_output.to_event_properties(),
    }
    distinct_id = (
        str(observation.triggered_by_user_id)
        if observation.triggered_by_user_id is not None
        and observation.triggered_by in (ObservationTrigger.ON_DEMAND, ObservationTrigger.RETRY)
        else replay_vision_distinct_id(observation.team_id)
    )

    result = capture_internal(
        token=team.api_token,
        event_name=_EVENT_NAME,
        event_source=_EVENT_SOURCE,
        distinct_id=distinct_id,
        # Stamp the event at scan-create time, not wall-clock, so a backfilled event lands on the day the
        # observation actually happened rather than clustering at reconcile time on the trend charts.
        timestamp=observation.created_at or datetime.now(UTC),
        properties=properties,
        process_person_profile=False,
        # Make the captured event UUID equal to observation.id so the admin UI can link back to it directly.
        event_uuid=str(observation.id),
    )
    result.raise_for_status()
    # Record the successful emit so the reconciler's backfill can tell this row apart from one that drifted.
    ReplayObservation.objects.filter(pk=observation.id).update(event_emitted_at=datetime.now(UTC))
