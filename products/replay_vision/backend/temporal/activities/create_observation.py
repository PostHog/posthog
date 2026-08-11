from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

import psycopg.errors
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models.organization import OrganizationMembership

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.enqueue_claims import release_enqueue_claim
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.replay_scanner_backfill import BackfillStatus, ReplayScannerBackfill
from products.replay_vision.backend.quota import quota_state
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_consent_skip, record_quota_exhausted_skip
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot, ScannerSnapshot
from products.replay_vision.backend.temporal.types import CreateObservationInputs, CreateObservationOutput


def _build_scanner_snapshot(scanner: ReplayScanner) -> dict[str, Any]:
    return ScannerSnapshot.from_scanner(scanner).model_dump(mode="json")


@activity.defn
@track_activity()
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the full scanner state and INSERT the row in `pending`; UNIQUE conflicts return `was_created=False` unless the row is this workflow's own lost-result insert, which is reclaimed."""
    try:
        return _create_observation(inputs)
    finally:
        # Every exit resolves the row's existence, so the enqueue claim is done; TTL covers a crash.
        release_enqueue_claim(
            team_id=inputs.team_id,
            scanner_id=inputs.scanner_id,
            workflow_id=inputs.workflow_id,
            backfill_id=inputs.backfill_id,
        )


def _create_observation(inputs: CreateObservationInputs) -> CreateObservationOutput:
    # team__organization is prefetched for the AI-consent check below.
    scanner = (
        # `all_origins`: this is the persistence step for every scan, inline ones included.
        ReplayScanner.all_origins.filter(pk=inputs.scanner_id, team_id=inputs.team_id)
        .select_related("team", "team__organization")
        .first()
    )
    if scanner is None:
        raise ValueError(f"ReplayScanner {inputs.scanner_id} not found for team {inputs.team_id}")

    backfill = None
    if inputs.backfill_id is not None:
        backfill = ReplayScannerBackfill.objects.for_team(inputs.team_id).filter(pk=inputs.backfill_id).first()
        if backfill is None or backfill.scanner_id != scanner.id:
            raise ValueError(f"ReplayScannerBackfill {inputs.backfill_id} not found for scanner {inputs.scanner_id}")
        if backfill.status == BackfillStatus.CANCELLED:
            # Cancelled between dispatch and persistence — honor the cancel instead of creating a row.
            activity.logger.info(
                "Skipping observation: backfill cancelled",
                extra={"backfill_id": str(inputs.backfill_id), "session_id": inputs.session_id},
            )
            return CreateObservationOutput(observation_id=None, was_created=False, scanner_type=scanner.scanner_type)

    # No AI processing of recordings without organization consent, even for scanners created earlier.
    if not scanner.team.organization.is_ai_data_processing_approved:
        record_consent_skip(scanner.scanner_type)
        activity.logger.info(
            "Skipping observation: AI data processing not approved for organization",
            extra={"scanner_id": str(inputs.scanner_id), "team_id": inputs.team_id, "session_id": inputs.session_id},
        )
        return CreateObservationOutput(
            observation_id=None,
            was_created=False,
            scanner_type=scanner.scanner_type,
        )

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

    # Backfill applies run the frozen config, not the scanner's current one.
    if backfill is not None:
        frozen = BackfillScannerSnapshot.load_for_backfill(backfill.id, backfill.scanner_snapshot)
        snapshot_dict = frozen.to_observation_snapshot().model_dump(mode="json")
        priced_model = frozen.model
    else:
        snapshot_dict = _build_scanner_snapshot(scanner)
        priced_model = scanner.model

    # Deliberately check-then-act: the snapshot doesn't count enqueue claims, so a concurrent burst can
    # overshoot by at most the in-flight caps allow, which is accepted.
    if quota_state(scanner.team.organization_id).would_exceed(observation_credits_for_model(priced_model)):
        record_quota_exhausted_skip(scanner.scanner_type)
        activity.logger.info(
            "Skipping observation: monthly quota exhausted",
            extra={"scanner_id": str(inputs.scanner_id), "team_id": inputs.team_id, "session_id": inputs.session_id},
        )
        return CreateObservationOutput(
            observation_id=None,
            was_created=False,
            scanner_type=scanner.scanner_type,
        )

    # Shared by the insert and the retake below, so a column added here can't be set on one path only.
    row_fields: dict[str, Any] = {
        "status": ObservationStatus.PENDING,
        # Required by `replay_observation_completed_at_matches_status`: a pending row must carry no
        # completion time, and a retaken row arrives with the failed attempt's still set.
        "completed_at": None,
        # Every period window keys off this: the in-flight reservation, and the usage receipt written on
        # success. A retaken row that kept its original stamp would bill this scan into the period the
        # first attempt ran in, which may be closed, so the credits would escape the current cap.
        # `auto_now_add` ignores this on insert and takes it on update, which is what each path needs.
        "created_at": timezone.now(),
        "workflow_id": inputs.workflow_id,
        "scanner_snapshot": snapshot_dict,
        "triggered_by": inputs.triggered_by,
        "triggered_by_user_id": inputs.triggered_by_user_id,
        "backfill": backfill,
    }

    try:
        with transaction.atomic():
            observation = ReplayObservation.objects.create(
                scanner=scanner,
                team=scanner.team,
                session_id=inputs.session_id,
                **row_fields,
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
        # A backfill quotes every session without a success event, which includes ones whose earlier scan
        # failed. Returning the failed row unchanged would let the walk report progress for a scan that never
        # re-ran, so retake the row instead. Filtered on FAILED so a concurrent success or a live-sweep
        # apply wins and this becomes a no-op.
        retaken = bool(
            backfill is not None
            and existing.status == ObservationStatus.FAILED
            and ReplayObservation.objects.filter(pk=existing.pk, status=ObservationStatus.FAILED).update(**row_fields)
        )
        # A still-PENDING row stamped with our own workflow id is our earlier lost-result insert — reclaim it.
        reclaimed = existing.workflow_id == inputs.workflow_id and existing.status == ObservationStatus.PENDING
        return CreateObservationOutput(
            observation_id=existing.id,
            was_created=retaken or reclaimed,
            scanner_type=existing_snapshot.scanner_type,
        )

    return CreateObservationOutput(
        observation_id=observation.id,
        was_created=True,
        scanner_type=scanner.scanner_type,
    )
