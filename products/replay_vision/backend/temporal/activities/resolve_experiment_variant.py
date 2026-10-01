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
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.replay_vision.backend.error_kinds import IneligibleSessionKind
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, IneligibleSessionError, ScannerFailureError
from products.replay_vision.backend.temporal.snapshots import ScannerSnapshot
from products.replay_vision.backend.temporal.types import ResolveExperimentVariantInputs, ResolveExperimentVariantOutput

logger = structlog.get_logger(__name__)

# The context is stored in the workflow history twice (this activity's result and the provider
# call's input), and an experiment description has no length bound of its own. Enough for the
# prompt to know what the experiment tests; anything longer adds history weight, not signal.
_MAX_DESCRIPTION_CHARS = 2_000


@activity.defn
@track_activity()
async def resolve_experiment_variant_activity(inputs: ResolveExperimentVariantInputs) -> ResolveExperimentVariantOutput:
    return await database_sync_to_async(_resolve, thread_sensitive=False)(inputs)


def _resolve(inputs: ResolveExperimentVariantInputs) -> ResolveExperimentVariantOutput:
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from rest_framework.exceptions import ValidationError as DRFValidationError  # noqa: PLC0415

    from products.experiments.backend.facade.replay import (  # noqa: PLC0415
        EXPOSURES_STILL_COMPUTING_MESSAGE,
        experiment_prompt_context,
        resolve_exposure_linkage,
        session_attribution,
        validate_experiment_exposure_access,
    )

    observation = (
        ReplayObservation.objects.filter(pk=inputs.observation_id, team_id=inputs.team_id)
        .select_related("scanner__created_by")
        .first()
    )
    if observation is None:
        raise ScannerFailureError(
            f"ReplayObservation {inputs.observation_id} not found for team {inputs.team_id}",
            kind=FailureKind.INTERNAL_ERROR,
        )
    snapshot = ScannerSnapshot.load_for(inputs.observation_id, observation.scanner_snapshot)
    scope = snapshot.experiment_scope()
    experiment_id = (scope or {}).get("experiment_id")
    if experiment_id is None:
        return ResolveExperimentVariantOutput(applicable=False)

    team = Team.objects.get(pk=inputs.team_id)
    try:
        # The same object-level check every other exposure read runs, as the principal this scan
        # acts for: whoever triggered it, else the scanner's creator (the principal the sweep's
        # candidate query already authorized).
        validate_experiment_exposure_access(team, _principal(observation), experiment_id)
        linkage = resolve_exposure_linkage(
            team,
            experiment_id=experiment_id,
            variant=scope.get("variant") if scope else None,
            variants=scope.get("variants") if scope else None,
        )
    except UserAccessControlError as exc:
        raise IneligibleSessionError(
            "The scan's principal no longer has access to this experiment",
            kind=IneligibleSessionKind.EXPERIMENT_UNRESOLVED,
        ) from exc
    except DRFValidationError as exc:
        if EXPOSURES_STILL_COMPUTING_MESSAGE in str(exc.detail):
            # Transient: the precomputation finishes on its own, so the retry policy owns this
            # rather than the session being failed for good.
            raise ScannerFailureError(EXPOSURES_STILL_COMPUTING_MESSAGE, kind=FailureKind.INFRA_TRANSIENT) from exc
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
    attribution = session_attribution(linkage, distinct_id) if distinct_id else None
    if attribution is None:
        raise IneligibleSessionError(
            "This session's user is not attributed to a watched variant of the experiment",
            kind=IneligibleSessionKind.NOT_EXPOSED,
        )
    # The bound the recordings list enforces in-query: a session that ended before the person's
    # first exposure shows behavior the experiment can't have caused. The sweep never selects one,
    # but a manual observe on an older session reaches here.
    if attribution.first_exposure_time is not None and metadata["end_time"] < attribution.first_exposure_time:
        raise IneligibleSessionError(
            "This session ended before the user's first exposure to the experiment",
            kind=IneligibleSessionKind.NOT_EXPOSED,
        )

    context = experiment_prompt_context(team, experiment_id=experiment_id)
    context_dict = dataclasses.asdict(context) if context is not None else None
    if context_dict and context_dict.get("description"):
        context_dict["description"] = context_dict["description"][:_MAX_DESCRIPTION_CHARS]
    return ResolveExperimentVariantOutput(
        applicable=True,
        experiment_variant=attribution.variant,
        session_duration_s=float(metadata["duration"]),
        experiment_context=context_dict,
    )


def _principal(observation: ReplayObservation) -> User | None:
    if observation.triggered_by_user_id is not None:
        triggering_user = User.objects.filter(pk=observation.triggered_by_user_id).first()
        if triggering_user is not None:
            return triggering_user
    return observation.scanner.created_by if observation.scanner is not None else None
