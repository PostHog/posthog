"""Projected state — the git ref a trial validates against.

This is the only thing that differs between strategies:

    optimistic → master HEAD
    serial     → master + the single predecessor ahead in the partition line

Speculative (master + all in-flight predecessors up to depth) and batched come later.
"""

from dataclasses import dataclass

from django.db.models import Q

from products.merge_queue.backend.models import EnrollmentState, Slot, SlotState, Strategy


@dataclass(frozen=True)
class ProjectedState:
    base_sha: str  # master HEAD
    predecessor_shas: list[str]  # in-flight predecessors folded into the projection


# slots still occupying a position ahead of us count as predecessors
_ACTIVE_AHEAD = (SlotState.ENROLLED, SlotState.TRIALING, SlotState.GREEN)


def strictly_ahead(slot: Slot) -> Q:
    """`(enqueued_at, id)` strictly before `slot` — the line ordering key."""
    return Q(enqueued_at__lt=slot.enqueued_at) | (Q(enqueued_at=slot.enqueued_at) & Q(id__lt=slot.id))


def predecessor_slot(slot: Slot) -> Slot | None:
    """The single slot immediately ahead of `slot` in its partition line (None at the head)."""
    return (
        Slot.objects.filter(
            partition_id=slot.partition_id,
            state__in=_ACTIVE_AHEAD,
            enrollment__state=EnrollmentState.ACTIVE,  # a merged/ejected enrollment leaves the line
        )
        .filter(strictly_ahead(slot))
        .order_by("-enqueued_at", "-id")
        .first()
    )


def build(slot: Slot, strategy: Strategy, *, master_head_sha: str) -> ProjectedState:
    """Compute the projected state `slot` should be validated against under `strategy`."""
    if strategy is Strategy.OPTIMISTIC:
        return ProjectedState(base_sha=master_head_sha, predecessor_shas=[])

    if strategy is Strategy.SERIAL:
        predecessor = predecessor_slot(slot)
        shas = [predecessor.enrollment.head_sha] if predecessor is not None else []
        return ProjectedState(base_sha=master_head_sha, predecessor_shas=shas)

    raise ValueError(f"strategy not currently supported: {strategy}")
