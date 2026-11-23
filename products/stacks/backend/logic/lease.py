"""The push lease: one attempt holds a stack while its worker runs, and an expired one is taken over.

Admission takes the lease for one attempt, with a generation one higher than the last. The worker claims and
extends it while it runs, and proves it at every saved record. A lease that expires is taken over: the attempt
becomes uncertain, its token is revoked, and the next push waits until a diff has seen what PostHog holds.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import DateTimeField, DurationField, ExpressionWrapper, Value
from django.db.models.functions import Now
from django.utils import timezone

import structlog

from ..db import WRITER_DB
from ..facade.contracts import StackServiceError
from ..facade.enums import DiffStatus, PushStatus, StackErrorKind
from ..models import Stack
from . import credentials, records

logger = structlog.get_logger(__name__)

# Covers the wait in the queue. The worker extends the lease once it starts.
ADMISSION_LEASE = timedelta(minutes=10)
# How long one extension lasts. The worker extends it every HEARTBEAT.
RUNNING_LEASE = timedelta(minutes=3)
HEARTBEAT = timedelta(seconds=30)


def locked_error() -> StackServiceError:
    return StackServiceError(
        StackErrorKind.CONFLICT,
        "stack_locked",
        "A push is running for this stack. Wait for it to finish, then try again.",
    )


def _in(duration: timedelta) -> ExpressionWrapper:
    """The database's clock plus `duration`. Every lease time is the database's, never a worker's."""
    return ExpressionWrapper(Now() + Value(duration, output_field=DurationField()), output_field=DateTimeField())


def lease_is_live(stack: Stack) -> bool:
    """Whether the stack's current attempt holds an unexpired lease, by the database's clock."""
    if stack.lease_attempt_id is None:
        return False
    return (
        records.stacks(stack.team_id)
        .filter(id=stack.id, lease_attempt_id=stack.lease_attempt_id, lease_expires_at__gt=Now())
        .exists()
    )


def holds(stack: Stack, attempt_id: UUID, generation: int) -> Stack | None:
    """The stack row, locked, while this attempt holds an unexpired lease of this generation. Call in a transaction."""
    return (
        records.stacks(stack.team_id)
        .select_for_update()
        .filter(id=stack.id, lease_attempt_id=attempt_id, lease_generation=generation, lease_expires_at__gt=Now())
        .first()
    )


def check_unlocked(stack: Stack) -> None:
    """Refuse a binding change while a push holds the stack. Call with the stack row locked, after
    `recover_if_expired` ran outside the transaction."""
    if stack.lease_attempt_id is not None:
        raise locked_error()


def recover_if_expired(stack: Stack) -> None:
    """Take over the stack's attempt if its lease expired.

    Runs in its own transaction, before the request that found the expired lease opens its own, so refusing that
    request never rolls back the takeover.
    """
    if stack.lease_attempt_id is not None and not lease_is_live(stack):
        take_over(stack, stack.lease_attempt_id)


def claim(stack: Stack, attempt_id: UUID, generation: int) -> bool:
    """The worker starts: prove the attempt still holds the lease and extend it."""
    return extend(stack.team_id, stack.id, attempt_id, generation)


def extend(team_id: int, stack_id: UUID, attempt_id: UUID, generation: int) -> bool:
    """Extend an unexpired lease. An expired one is never revived, because a takeover may already be under way."""
    return bool(
        records.stacks(team_id)
        .filter(id=stack_id, lease_attempt_id=attempt_id, lease_generation=generation, lease_expires_at__gt=Now())
        .update(lease_expires_at=_in(RUNNING_LEASE))
    )


def register_token(stack: Stack, attempt_id: UUID, generation: int, token_id: UUID) -> bool:
    """Record the run's token for the attempt while it holds the lease, before the engine gets the credential.

    A takeover then always finds the token to revoke. False means the lease is gone, and the caller revokes the
    token itself and stops.
    """
    with transaction.atomic(using=WRITER_DB):
        if holds(stack, attempt_id, generation) is None:
            return False
        records.diffs(stack.team_id).filter(push_attempt_id=attempt_id).update(push_token_id=token_id)
    return True


def close_attempt(
    stack: Stack,
    attempt_id: UUID,
    errors: list[dict],
    *,
    status: PushStatus,
    adopted: frozenset[tuple[str, str]] = frozenset(),
    generation: int | None = None,
) -> bool:
    """Close one attempt: bind what its last saved record holds, set the diff's outcome and release the lease.

    Does nothing when the attempt no longer holds the lease, because the takeover already closed it. A worker
    passes its `generation`: if its lease expired, the outcome it reports may race a takeover, so the attempt
    closes as uncertain instead.
    """
    with transaction.atomic(using=WRITER_DB):
        current = records.locked_stack(stack)
        if current.lease_attempt_id != attempt_id:
            return False
        if generation is not None and holds(current, attempt_id, generation) is None:
            errors, status = [interrupted_error()], PushStatus.UNCERTAIN
        diff = records.diffs(stack.team_id).select_for_update().filter(push_attempt_id=attempt_id).first()
        if diff is None:
            records.stacks(stack.team_id).filter(id=stack.id).update(lease_attempt_id=None, lease_expires_at=None)
            return False
        moved = records.attempt_saved_a_record(stack.team_id, attempt_id)
        errors = list(errors)
        if moved:
            try:
                record = records.latest_record(current)
            except records.RecordMissing:
                errors.append(records.record_missing_error())
                record = None
            if record is not None:
                errors.extend(records.rebuild_bindings(current, diff, records.description_of(diff), record, adopted))
            records.stale_ready_diffs(current, keep=diff.id)
            # A newer push makes every older saved diff of the stack unpushable, so none keeps its bytes.
            records.diffs(stack.team_id).filter(stack_id=stack.id).exclude(id=diff.id).exclude(
                encrypted_saved_diff=None
            ).update(encrypted_saved_diff=None)
        # An uncertain attempt may have created what it reserved, so the reservation stays until a later push.
        if status != PushStatus.UNCERTAIN:
            records.release_natural(current)
        if status == PushStatus.SUCCEEDED and errors:
            status = PushStatus.FAILED
        if status == PushStatus.SUCCEEDED:
            diff_status = DiffStatus.PUSHED
        elif moved or status == PushStatus.UNCERTAIN:
            diff_status = DiffStatus.STALE
        else:
            diff_status = DiffStatus.READY
        records.diffs(stack.team_id).filter(id=diff.id).update(
            status=diff_status.value,
            push_status=status.value,
            push_errors=errors,
            push_finished_at=timezone.now(),
            encrypted_saved_diff=diff.encrypted_saved_diff if diff_status == DiffStatus.READY else None,
        )
        stack_update: dict = {"lease_attempt_id": None, "lease_expires_at": None}
        if status == PushStatus.UNCERTAIN:
            stack_update["needs_reconcile"] = True
            stack_update["revision"] = current.revision + 1
            # Entities the attempt may have made without recording them were made after it started.
            if not current.needs_reconcile or current.uncertain_since is None:
                stack_update["uncertain_since"] = diff.push_started_at or Now()
        records.stacks(stack.team_id).filter(id=stack.id).update(**stack_update)
        token_id = diff.push_token_id
    credentials.revoke(token_id)
    return True


def interrupted_error() -> dict:
    return {
        "code": "push_interrupted",
        "message": "The push stopped before it reported what it changed. What it saved is kept. "
        "Run diff again to see what PostHog holds now.",
    }


def take_over(stack: Stack, attempt_id: UUID) -> bool:
    """Close an attempt whose lease expired, in a transaction of its own. Its worker may still be alive.

    The token is revoked before the attempt closes, and a failed revoke still closes it as uncertain. A request
    the old worker already sent can still complete after that: the uncertain stack waits for a reconcile.
    """
    with transaction.atomic(using=WRITER_DB):
        current = records.locked_stack(stack)
        if current.lease_attempt_id != attempt_id or lease_is_live(current):
            return False
        diff = records.diffs(stack.team_id).filter(push_attempt_id=attempt_id).first()
        if diff is not None and not credentials.revoke(diff.push_token_id):
            logger.error("stacks_takeover_revoke_failed", attempt_id=str(attempt_id))
        logger.warning("stacks_push_taken_over", attempt_id=str(attempt_id))
        return close_attempt(current, attempt_id, [interrupted_error()], status=PushStatus.UNCERTAIN)


def recover_expired_leases() -> int:
    """Close every attempt whose lease expired. The cleanup schedule runs this. One failure never stops the rest."""
    recovered = 0
    expired = Stack.all_teams.using(WRITER_DB).filter(lease_attempt_id__isnull=False, lease_expires_at__lt=Now())
    for stack in expired.only("id", "team_id", "lease_attempt_id"):
        try:
            if stack.lease_attempt_id is not None and take_over(stack, stack.lease_attempt_id):
                recovered += 1
        except Exception:
            logger.exception("stacks_lease_recovery_failed", stack_id=str(stack.id))
    return recovered
