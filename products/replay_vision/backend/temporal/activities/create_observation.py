from typing import Any
from uuid import UUID

from django.db import IntegrityError, OperationalError, connection, transaction
from django.db.models import F
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
from products.replay_vision.backend.quota import (
    BillingPeriod,
    ScannerBudget,
    compute_scanner_budget,
    current_period_bounds,
    quota_state,
)
from products.replay_vision.backend.temporal.constants import ADMISSION_BUDGET_TTL
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import SCANNER_ADMISSION_BUSY_ERROR_TYPE
from products.replay_vision.backend.temporal.metrics import (
    record_consent_skip,
    record_quota_exhausted_skip,
    record_scanner_admission_busy,
    record_scanner_limit_reached,
)
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot, ScannerSnapshot
from products.replay_vision.backend.temporal.types import CreateObservationInputs, CreateObservationOutput


def _build_scanner_snapshot(scanner: ReplayScanner) -> dict[str, Any]:
    return ScannerSnapshot.from_scanner(scanner).model_dump(mode="json")


@activity.defn
@track_activity()
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the full scanner state and INSERT the row in `pending`; UNIQUE conflicts return `was_created=False` unless the row is this workflow's own lost-result insert, which is reclaimed."""
    release_claim = True
    try:
        return _create_observation(inputs)
    except BaseException as e:
        # A busy admission keeps its claim: the retry lands in seconds, and decaying the claim here
        # would let dispatchers admit more applies into the very contention being backed off from.
        release_claim = not (isinstance(e, ApplicationError) and e.type == SCANNER_ADMISSION_BUSY_ERROR_TYPE)
        raise
    finally:
        # Every non-busy exit resolves the row's existence, so the claim is done; TTL covers a crash.
        if release_claim:
            release_enqueue_claim(
                team_id=inputs.team_id,
                scanner_id=inputs.scanner_id,
                workflow_id=inputs.workflow_id,
                backfill_id=inputs.backfill_id,
            )


def _try_cached_admission(scanner_pk: UUID, cost: int, period: BillingPeriod) -> bool:
    """One conditional UPDATE admits `cost` against the cached budget; no aggregates, no explicit lock.

    Concurrent UPDATEs serialize on the row for one statement each, and Postgres re-evaluates the
    WHERE against the latest committed row after a lock wait, so two racing admissions cannot both
    spend the last headroom. False means the cache is stale, the period rolled, the headroom ran
    out, or the cap was lifted; the locked refresh resolves which.
    """
    fresh_after = timezone.now() - ADMISSION_BUDGET_TTL
    return bool(
        ReplayScanner.all_origins.filter(
            pk=scanner_pk,
            credit_limit__isnull=False,
            admission_budget_period_start=period.start,
            admission_budget_refreshed_at__gte=fresh_after,
            credit_limit__gte=F("admission_budget_used") + F("admission_credits_since_refresh") + cost,
        ).update(admission_credits_since_refresh=F("admission_credits_since_refresh") + cost)
    )


def _admit_within_cap(scanner: ReplayScanner, cost: int, period: BillingPeriod) -> ScannerBudget | None:
    """Admit `cost` against the scanner's cap; None on admission, the refusing budget otherwise.

    A cache miss recomputes the spend aggregates under the row lock, rewrites the cache, and
    decides from the fresh figure, so the aggregates run once per TTL instead of once per admission.
    The admitting UPDATE and the observation INSERT share the caller's transaction, so a failed
    insert rolls its admission back.
    """
    # SET LOCAL covers the whole admission transaction: the fast-path UPDATE and the refresh lock
    # both give up after 2s and defer to the activity's backoff instead of camping in Postgres's
    # lock queue. The 2s grace absorbs the row's brief blocking holders (scanner save(),
    # prompt-suggestion apply), which NOWAIT would turn into instant admission failures.
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '2s'")
    if _try_cached_admission(scanner.pk, cost, period):
        return None
    locked = (
        # A contended refresh times out into the OperationalError handler below and retries on the
        # activity's backoff, and the retry usually lands on the winner's warm cache. By-pk via
        # all_origins, so a capped inline scanner locks its row rather than skipping enforcement.
        ReplayScanner.all_origins.select_for_update(of=("self",))
        .filter(pk=scanner.pk)
        .only("pk", "credit_limit")
        .first()
    )
    if locked is None or locked.credit_limit is None:
        # Uncapped (or deleted) by the time the lock resolved; nothing to enforce.
        return None
    budget = compute_scanner_budget(scanner, period)
    admitted = not budget.would_exceed(cost)
    ReplayScanner.all_origins.filter(pk=scanner.pk).update(
        admission_budget_used=budget.credits_used,
        admission_budget_refreshed_at=timezone.now(),
        admission_budget_period_start=period.start,
        # The reset supersedes every earlier increment: a fast-path admission holds its row lock to
        # commit, so this refresh either saw its committed in-flight row in the aggregates or timed
        # out against it — no admission can be uncommitted here with its increment surviving.
        admission_credits_since_refresh=cost if admitted else 0,
    )
    return None if admitted else budget


def _reclaim_own_pending_insert(inputs: CreateObservationInputs) -> CreateObservationOutput | None:
    """A still-PENDING row stamped with our own workflow id is our earlier lost-result insert."""
    existing = ReplayObservation.objects.filter(scanner_id=inputs.scanner_id, session_id=inputs.session_id).first()
    if existing is None or existing.workflow_id != inputs.workflow_id or existing.status != ObservationStatus.PENDING:
        return None
    # Route through the validator so a malformed legacy snapshot surfaces as a tagged non-retryable error.
    existing_snapshot = ScannerSnapshot.load_for(existing.id, existing.scanner_snapshot)
    return CreateObservationOutput(
        observation_id=existing.id,
        was_created=True,
        scanner_type=existing_snapshot.scanner_type,
    )


def _retake_failed_row(inputs: CreateObservationInputs, row_fields: dict[str, Any]) -> CreateObservationOutput | None:
    """Retake the session's FAILED row for a backfill, so the failed scan re-runs.

    Filtered on FAILED so a concurrent success wins and this no-ops."""
    retaken = ReplayObservation.objects.filter(
        scanner_id=inputs.scanner_id, session_id=inputs.session_id, status=ObservationStatus.FAILED
    ).update(**row_fields)
    if not retaken:
        return None
    existing = ReplayObservation.objects.get(scanner_id=inputs.scanner_id, session_id=inputs.session_id)
    # Route through the validator so a malformed snapshot surfaces as a tagged non-retryable error.
    existing_snapshot = ScannerSnapshot.load_for(existing.id, existing.scanner_snapshot)
    return CreateObservationOutput(
        observation_id=existing.id,
        was_created=True,
        scanner_type=existing_snapshot.scanner_type,
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
        # `replay_observation_completed_at_matches_status` requires a pending row to carry no completion time.
        "completed_at": None,
        # The reservation and the usage receipt both window off this, so a retake that kept the failed
        # attempt's stamp would bill into a period that may already be closed.
        "created_at": timezone.now(),
        "workflow_id": inputs.workflow_id,
        "scanner_snapshot": snapshot_dict,
        "triggered_by": inputs.triggered_by,
        "triggered_by_user_id": inputs.triggered_by_user_id,
        "backfill": backfill,
    }

    # Resolved before the transaction to shrink the in-transaction window; the period is stable for
    # the admission decision.
    period = current_period_bounds(scanner.team.organization_id) if scanner.credit_limit is not None else None
    # Priced from `priced_model` (the frozen snapshot model for backfills), matching what the
    # observation will actually charge, not the scanner's current model.
    cost = observation_credits_for_model(priced_model)
    try:
        with transaction.atomic():
            # Capped scanners admit against the cached admission budget so concurrent applies cannot
            # overshoot the cap; uncapped scanners keep the lock-free path.
            if scanner.credit_limit is not None:
                assert period is not None
                refused_budget = _admit_within_cap(scanner, cost, period)
                if refused_budget is not None:
                    # A retry's own first insert counts as in-flight spend, so reclaim it instead of
                    # stranding it PENDING. Only the own-reclaim case returns here; any other existing
                    # row (including a retakeable FAILED one, which would spend fresh budget) falls
                    # through to the capped skip.
                    reclaimed_output = _reclaim_own_pending_insert(inputs)
                    if reclaimed_output is not None:
                        return reclaimed_output
                    record_scanner_limit_reached("admission")
                    activity.logger.info(
                        "Skipping observation: scanner credit limit reached",
                        extra={
                            "scanner_id": str(inputs.scanner_id),
                            "team_id": inputs.team_id,
                            "session_id": inputs.session_id,
                            "credit_limit": refused_budget.credit_limit,
                            "credits_used": refused_budget.credits_used,
                        },
                    )
                    return CreateObservationOutput(
                        observation_id=None,
                        was_created=False,
                        scanner_type=scanner.scanner_type,
                    )
                # A retake spends fresh budget, so on a capped scanner it must commit in the same
                # transaction as its admission: a rolled-back retake then gives the credits back. It
                # cannot wait for the IntegrityError handler, which runs after the transaction aborted.
                if backfill is not None:
                    retaken_output = _retake_failed_row(inputs, row_fields)
                    if retaken_output is not None:
                        return retaken_output

            observation = ReplayObservation.objects.create(
                scanner=scanner,
                team=scanner.team,
                session_id=inputs.session_id,
                **row_fields,
            )
    except OperationalError as e:
        if not isinstance(e.__cause__, psycopg.errors.LockNotAvailable):
            raise
        record_scanner_admission_busy(scanner.scanner_type)
        activity.logger.info(
            "Scanner admission lock busy; deferring to activity retry",
            extra={
                "scanner_id": str(inputs.scanner_id),
                "team_id": inputs.team_id,
                "session_id": inputs.session_id,
            },
        )
        raise ApplicationError(
            "Scanner admission lock busy; retried with backoff",
            type=SCANNER_ADMISSION_BUSY_ERROR_TYPE,
        ) from e
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
        # A backfill quotes sessions whose earlier scan failed, so retake that row rather than report progress
        # for a scan that never re-runs. Capped scanners retake under the admission lock before the insert;
        # this unlocked path serves uncapped scanners, which tolerate no lock on admission either.
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
