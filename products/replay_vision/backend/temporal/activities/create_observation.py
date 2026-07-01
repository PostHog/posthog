from typing import Any

from django.db import IntegrityError, transaction

import psycopg.errors
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models.organization import OrganizationMembership

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.types import (
    CreateObservationInputs,
    CreateObservationOutput,
    ScannerSnapshot,
)


def _build_scanner_snapshot(scanner: ReplayScanner) -> dict[str, Any]:
    return ScannerSnapshot(
        name=scanner.name,
        scanner_type=scanner.scanner_type,
        scanner_version=scanner.scanner_version,
        model=scanner.model,
        provider=scanner.provider,
        emits_signals=scanner.emits_signals,
        scanner_config=scanner.scanner_config,
    ).model_dump(mode="json")


@activity.defn
@track_activity()
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the full scanner state and INSERT the row in `pending`.

    Returns `was_created=False` on UNIQUE conflict, unless the conflicting row is this workflow's own
    earlier lost-result insert, which is reclaimed as `was_created=True`.
    """
    scanner = ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id).select_related("team").first()
    if scanner is None:
        raise ValueError(f"ReplayScanner {inputs.scanner_id} not found for team {inputs.team_id}")

    if inputs.triggered_by_user_id is not None:
        # The activity is the persistence boundary, so re-check team membership rather than trusting the trigger.
        is_member = OrganizationMembership.objects.filter(
            user_id=inputs.triggered_by_user_id,
            organization_id=scanner.team.organization_id,
        ).exists()
        if not is_member:
            raise ValueError(
                f"User {inputs.triggered_by_user_id} is not a member of scanner {inputs.scanner_id}'s organization"
            )

    if compute_quota_snapshot(scanner.team.organization_id).exhausted:
        activity.logger.info(
            "Skipping observation: monthly quota exhausted",
            extra={"scanner_id": str(inputs.scanner_id), "team_id": inputs.team_id, "session_id": inputs.session_id},
        )
        return CreateObservationOutput(
            observation_id=None,
            was_created=False,
            scanner_type=scanner.scanner_type,
        )

    try:
        with transaction.atomic():
            observation = ReplayObservation.objects.create(
                scanner=scanner,
                team=scanner.team,
                session_id=inputs.session_id,
                status=ObservationStatus.PENDING,
                workflow_id=inputs.workflow_id,
                scanner_snapshot=_build_scanner_snapshot(scanner),
                triggered_by=inputs.triggered_by,
                triggered_by_user_id=inputs.triggered_by_user_id,
            )
    except IntegrityError as e:
        # Only swallow the dedup case; FK / CHECK violations should fail the activity.
        if not isinstance(e.__cause__, psycopg.errors.UniqueViolation):
            raise
        existing = ReplayObservation.objects.filter(scanner_id=inputs.scanner_id, session_id=inputs.session_id).first()
        if existing is None:
            # Conflicting row was deleted between INSERT and SELECT; let Temporal retry the INSERT.
            raise ApplicationError(
                f"Observation for ({inputs.scanner_id}, {inputs.session_id}) was deleted mid-create",
                non_retryable=False,
            )
        # Route through the validator so a malformed legacy snapshot surfaces as a tagged non-retryable error.
        existing_snapshot = ScannerSnapshot.load_for(existing.id, existing.scanner_snapshot)
        # A still-PENDING row stamped with our own workflow id is our earlier insert whose activity result
        # was lost — reclaim it instead of leaving it orphaned in `pending` forever.
        reclaimed = existing.workflow_id == inputs.workflow_id and existing.status == ObservationStatus.PENDING
        return CreateObservationOutput(
            observation_id=existing.id,
            was_created=reclaimed,
            scanner_type=existing_snapshot.scanner_type,
        )

    return CreateObservationOutput(
        observation_id=observation.id,
        was_created=True,
        scanner_type=scanner.scanner_type,
    )
