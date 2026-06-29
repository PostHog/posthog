"""Imperative facade surface.

All queue mutation goes through these functions; each emits the matching `QueueEvent`.
Synchronous (Django ORM); `enroll` starts the trial workflow fire-and-forget via the
lifecycle. This module — with `types.py` and `decisions.py` — is the only surface that
Cowboy, the channels, and the shadow harness may import.
"""

from django.db import transaction
from django.utils import timezone

from products.merge_queue.backend import observability
from products.merge_queue.backend.engine import lifecycle
from products.merge_queue.backend.engine.projected_state import strictly_ahead
from products.merge_queue.backend.facade.types import Actor, ActorKind, EnrollmentStatus, PRRef, Scope, SlotStatus
from products.merge_queue.backend.models import Enrollment, EnrollmentState, Partition, QueueEventType, Slot


# ---- exceptions ----
class FacadeError(Exception): ...


class AlreadyEnrolled(FacadeError): ...


class NotEnrolled(FacadeError): ...


class NotEligible(FacadeError): ...


class NoMatchingPartition(FacadeError): ...


class PartitionFrozen(FacadeError): ...


class NotHumanActor(FacadeError):  # raised only by break_glass
    ...


# ---- imperative surface ----
def enroll(pr: PRRef, *, actor: Actor, approval_ref: str = "") -> EnrollmentStatus:
    """Admit an eligible PR. Routes to its safe-set partition(s), creates Enrollment + Slot(s),
    emits ENROLLED. Raises AlreadyEnrolled / NoMatchingPartition.

    Eligibility (approved ∧ checks-green ∧ partition predicate) is resolved by the GitHub
    adapter before it calls enroll; `NotEligible` is reserved for that path.
    """
    if _active_enrollment(pr.repo, pr.number) is not None:
        raise AlreadyEnrolled(f"{pr.repo}#{pr.number} already has an active enrollment")

    partitions = _resolve_partitions(pr)
    if not partitions:
        raise NoMatchingPartition(f"{pr.repo}#{pr.number} matches no partition")

    # currently routes to a single partition; partition-spanning routing (multi-slot) comes later.
    enrollment = lifecycle.enroll_pr(pr, actor=actor, partition=partitions[0], approval_ref=approval_ref)
    return _to_status(enrollment)


def dequeue(pr: PRRef, *, actor: Actor, reason: str) -> None:
    """Remove an active enrollment. Emits DEQUEUED. Raises NotEnrolled."""
    enrollment = _active_enrollment(pr.repo, pr.number)
    if enrollment is None:
        raise NotEnrolled(f"{pr.repo}#{pr.number} is not enrolled")
    partition = _partition_of(enrollment)
    with transaction.atomic():
        enrollment.state = EnrollmentState.DEQUEUED
        enrollment.save(update_fields=["state", "updated_at"])
        observability.emit(
            QueueEventType.DEQUEUED, actor=actor, enrollment=enrollment, partition=partition, payload={"reason": reason}
        )
    if partition is not None:
        lifecycle.advance(partition)


def status(pr: PRRef) -> EnrollmentStatus | None:
    """Read-only. None if the PR has no active enrollment."""
    enrollment = _active_enrollment(pr.repo, pr.number)
    return _to_status(enrollment) if enrollment is not None else None


def freeze(scope: Scope, *, actor: Actor) -> None:
    """Pause merges for a partition or the whole queue. In-flight trials FINISH. Emits FROZEN."""
    for partition in _scoped_partitions(scope):
        if partition.is_frozen:
            continue
        partition.frozen_at = timezone.now()
        partition.frozen_by_id = actor.id
        partition.frozen_by_kind = str(actor.kind)
        partition.save(update_fields=["frozen_at", "frozen_by_id", "frozen_by_kind", "updated_at"])
        observability.emit(QueueEventType.FROZEN, actor=actor, partition=partition)


def unfreeze(scope: Scope, *, actor: Actor) -> None:
    """Resume; merging continues from persisted trial results. Emits UNFROZEN."""
    for partition in _scoped_partitions(scope):
        if not partition.is_frozen:
            continue
        partition.frozen_at = None
        partition.frozen_by_id = None
        partition.frozen_by_kind = None
        partition.save(update_fields=["frozen_at", "frozen_by_id", "frozen_by_kind", "updated_at"])
        observability.emit(QueueEventType.UNFROZEN, actor=actor, partition=partition)
        lifecycle.advance(partition)


def break_glass(pr: PRRef, *, actor: Actor) -> None:
    """Human-only forced merge / queue bypass. Emits BREAK_GLASS_USED.

    Raises NotHumanActor if `actor.kind` is not HUMAN — the one hard authz check.
    """
    if not actor.is_human:
        raise NotHumanActor("break_glass is human-only; agents and Cowboy may never use it")

    enrollment = _active_enrollment(pr.repo, pr.number)
    partition = _partition_of(enrollment)
    # shadow-guarded forced merge — currently records, does not act
    lifecycle.shadow_guard().merge(repo=pr.repo, number=pr.number, sha=pr.head_sha)
    with transaction.atomic():
        if enrollment is not None:
            enrollment.state = EnrollmentState.MERGED
            enrollment.merged_at = timezone.now()
            enrollment.save(update_fields=["state", "merged_at", "updated_at"])
        observability.emit(QueueEventType.BREAK_GLASS_USED, actor=actor, enrollment=enrollment, partition=partition)


# ---- internals ----
def _active_enrollment(repo: str, number: int) -> Enrollment | None:
    return Enrollment.objects.filter(repo=repo, number=number, state=EnrollmentState.ACTIVE).first()


def _partition_of(enrollment: Enrollment | None) -> Partition | None:
    if enrollment is None:
        return None
    slot = enrollment.slots.first()
    return slot.partition if slot is not None else None


def _resolve_partitions(pr: PRRef) -> list[Partition]:
    """Currently routes to a single partition (lowest precedence). The predicate-matching router
    that computes the full safe set (and partition-spanning PRs) comes later."""
    partition = Partition.objects.order_by("precedence", "id").first()
    return [partition] if partition is not None else []


def _scoped_partitions(scope: Scope) -> list[Partition]:
    if scope.partition is None:
        return list(Partition.objects.all())
    return list(Partition.objects.filter(name=scope.partition))


def _position(slot: Slot) -> int:
    return (
        Slot.objects.filter(partition_id=slot.partition_id, enrollment__state=EnrollmentState.ACTIVE)
        .filter(strictly_ahead(slot))
        .count()
    )


def _to_status(enrollment: Enrollment) -> EnrollmentStatus:
    slots = [
        SlotStatus(
            partition=slot.partition.name,
            state=slot.state,
            position=_position(slot),
            current_trial_id=slot.current_trial_id,
            projected_base_sha=slot.projected_base_sha,
        )
        for slot in enrollment.slots.select_related("partition").all()
    ]
    return EnrollmentStatus(
        pr=PRRef(repo=enrollment.repo, number=enrollment.number, head_sha=enrollment.head_sha),
        state=enrollment.state,
        slots=slots,
        enrolled_by=Actor(id=enrollment.enrolled_by_id, kind=ActorKind(enrollment.enrolled_by_kind)),
        blocked_by=None,  # unlanded stack parent — stacks are surfaced later
        eject_count=enrollment.eject_count,
        cycle_count=enrollment.cycle_count,
        enrolled_at=enrollment.created_at,
    )
