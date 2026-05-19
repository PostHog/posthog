from typing import Any

from django.db import IntegrityError, transaction

import psycopg.errors
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models.organization import OrganizationMembership

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import CreateObservationInputs, CreateObservationOutput, LensSnapshot


def _build_lens_snapshot(lens: ReplayLens) -> dict[str, Any]:
    return LensSnapshot(
        name=lens.name,
        lens_type=lens.lens_type,
        lens_version=lens.lens_version,
        model=lens.model,
        provider=lens.provider,
        emits_signals=lens.emits_signals,
        lens_config=lens.lens_config,
    ).model_dump(mode="json")


@activity.defn
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the full lens state and INSERT the row in `pending`. Returns `was_created=False` on UNIQUE conflict."""
    lens = ReplayLens.objects.filter(pk=inputs.lens_id, team_id=inputs.team_id).select_related("team").first()
    if lens is None:
        raise ValueError(f"ReplayLens {inputs.lens_id} not found for team {inputs.team_id}")

    if inputs.triggered_by_user_id is not None:
        # The activity is the persistence boundary, so re-check team membership rather than trusting the trigger.
        is_member = OrganizationMembership.objects.filter(
            user_id=inputs.triggered_by_user_id,
            organization_id=lens.team.organization_id,
        ).exists()
        if not is_member:
            raise ValueError(
                f"User {inputs.triggered_by_user_id} is not a member of lens {inputs.lens_id}'s organization"
            )

    try:
        with transaction.atomic():
            observation = ReplayObservation.objects.create(
                lens=lens,
                team=lens.team,
                session_id=inputs.session_id,
                status=ObservationStatus.PENDING,
                workflow_id=inputs.workflow_id,
                lens_snapshot=_build_lens_snapshot(lens),
                triggered_by=inputs.triggered_by,
                triggered_by_user_id=inputs.triggered_by_user_id,
            )
    except IntegrityError as e:
        # Only swallow the dedup case; FK / CHECK violations should fail the activity.
        if not isinstance(e.__cause__, psycopg.errors.UniqueViolation):
            raise
        existing = ReplayObservation.objects.filter(lens_id=inputs.lens_id, session_id=inputs.session_id).first()
        if existing is None:
            # Conflicting row was deleted between INSERT and SELECT; let Temporal retry the INSERT.
            raise ApplicationError(
                f"Observation for ({inputs.lens_id}, {inputs.session_id}) was deleted mid-create",
                non_retryable=False,
            )
        return CreateObservationOutput(observation_id=existing.id, was_created=False)

    return CreateObservationOutput(observation_id=observation.id, was_created=True)
