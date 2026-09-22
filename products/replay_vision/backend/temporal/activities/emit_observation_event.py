"""Emit the `$recording_observed` event with the scanner output to the customer's events table."""

from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.api.capture import capture_internal
from posthog.models.group_type_mapping import get_group_types_for_project
from posthog.models.team import Team
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError
from products.replay_vision.backend.temporal.types import EmitObservationEventInputs, ScannerSnapshot

logger = structlog.get_logger(__name__)

_EVENT_NAME = "$recording_observed"
_EVENT_SOURCE = "replay_vision"


@activity.defn
@track_activity(side_effect="event")
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
        # Priced at emit time, so it can drift from quota.py's repriced-at-current-rates totals.
        "credits": observation_credits_for_model(snapshot.model),
        "emits_signals": snapshot.emits_signals,
        # Flatten scanner output so HogQL can query individual fields without a JSON extract.
        **inputs.model_output.to_event_properties(),
        **_group_properties(team, observation),
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
        timestamp=datetime.now(UTC),
        properties=properties,
        process_person_profile=False,
        # Make the captured event UUID equal to observation.id so the admin UI can link back to it directly.
        event_uuid=str(observation.id),
    )
    result.raise_for_status()


def _group_properties(team: Team, observation: ReplayObservation) -> dict:
    """Group attribution for the recorded session: `$group_N` for group analytics, `$groups` for readers.

    Ingestion only derives `$group_N` from `$groups` when it processes a person profile, which this event
    deliberately doesn't, so the indexed keys are written here directly (the same rewrite ingestion would do).
    """
    group_keys = observation.session_group_keys or {}
    if not group_keys:
        return {}
    properties: dict = {f"$group_{index}": key for index, key in group_keys.items()}
    try:
        index_to_type = {
            mapping["group_type_index"]: mapping["group_type"]
            for mapping in get_group_types_for_project(team.project_id, caller_tag="replay_vision/emit_observation")
        }
    except Exception:
        # Named groups are a nicety for webhook and alert consumers; the indexed keys above already carry
        # everything group analytics needs, so a group-type lookup failure must not lose them.
        logger.warning("replay_vision.emit.group_types_lookup_failed", observation_id=str(observation.id))
        return properties
    # `int(index)` because the stored map round-tripped through JSON, where object keys are always strings.
    named = {group_type: key for index, key in group_keys.items() if (group_type := index_to_type.get(int(index)))}
    if named:
        properties["$groups"] = named
    return properties
