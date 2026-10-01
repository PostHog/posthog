"""Resolve which variant an experiment scanner's session belongs to, before any model call.

The variant comes from the exposure data through the experiments facade, never from the model,
so the value the prompt names and the value the observation stores cannot disagree. A session
the exposure data does not attribute to a watched variant is ineligible at no credit cost.
"""

import dataclasses

import structlog
from temporalio import activity

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async

from products.replay_vision.backend.error_kinds import IneligibleSessionKind
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, IneligibleSessionError, ScannerFailureError
from products.replay_vision.backend.temporal.snapshots import ScannerSnapshot
from products.replay_vision.backend.temporal.types import ResolveExperimentVariantInputs, ResolveExperimentVariantOutput

logger = structlog.get_logger(__name__)


@activity.defn
@track_activity()
async def resolve_experiment_variant_activity(inputs: ResolveExperimentVariantInputs) -> ResolveExperimentVariantOutput:
    return await database_sync_to_async(_resolve, thread_sensitive=False)(inputs)


def _resolve(inputs: ResolveExperimentVariantInputs) -> ResolveExperimentVariantOutput:
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from rest_framework.exceptions import ValidationError as DRFValidationError  # noqa: PLC0415

    from products.experiments.backend.facade.replay import (  # noqa: PLC0415
        experiment_prompt_context,
        resolve_exposure_linkage,
        session_variant,
    )

    raw = (
        ReplayObservation.objects.filter(pk=inputs.observation_id, team_id=inputs.team_id)
        .values_list("scanner_snapshot", flat=True)
        .first()
    )
    if raw is None:
        raise ScannerFailureError(
            f"ReplayObservation {inputs.observation_id} not found for team {inputs.team_id}",
            kind=FailureKind.INTERNAL_ERROR,
        )
    snapshot = ScannerSnapshot.load_for(inputs.observation_id, raw)
    scope = snapshot.experiment_scope()
    experiment_id = (scope or {}).get("experiment_id")
    if experiment_id is None:
        return ResolveExperimentVariantOutput(applicable=False)

    team = Team.objects.get(pk=inputs.team_id)
    try:
        linkage = resolve_exposure_linkage(
            team,
            experiment_id=experiment_id,
            variant=scope.get("variant") if scope else None,
            variants=scope.get("variants") if scope else None,
        )
    except DRFValidationError as exc:
        raise IneligibleSessionError(
            f"The experiment's exposed population can't be resolved: {exc.detail}",
            kind=IneligibleSessionKind.EXPERIMENT_UNRESOLVED,
        ) from exc

    metadata = SessionReplayEvents().get_metadata(
        session_id=inputs.session_id, team=team, ch_user=ClickHouseUser.REPLAY_VISION
    )
    if metadata is None:
        # The same gate `fetch_session_events` applies; whichever of the two parallel activities
        # lands first fails the scan with the same reason.
        raise IneligibleSessionError("No replay metadata found", kind=IneligibleSessionKind.NO_RECORDING)
    distinct_id = metadata.get("distinct_id")
    variant = session_variant(linkage, distinct_id) if distinct_id else None
    if variant is None:
        raise IneligibleSessionError(
            "This session's user is not attributed to a watched variant of the experiment",
            kind=IneligibleSessionKind.NOT_EXPOSED,
        )

    context = experiment_prompt_context(team, experiment_id=experiment_id)
    return ResolveExperimentVariantOutput(
        applicable=True,
        experiment_variant=variant,
        session_duration_s=float(metadata["duration"]),
        experiment_context=dataclasses.asdict(context) if context is not None else None,
    )
