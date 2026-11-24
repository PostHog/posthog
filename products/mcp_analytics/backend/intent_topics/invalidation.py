from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import IntentInvalidationConflict
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentWriteBarrier


class IntentWritesFrozen(Exception):
    pass


@dataclass(frozen=True)
class BarrierSnapshot:
    generation: int
    frozen: bool


@contextmanager
def _locked_barrier(team: Team) -> Iterator[MCPIntentWriteBarrier]:
    project = team.parent_team or team
    # Admission must commit before a caller reads sources or sends a remote write.
    with team_scope(project.pk, canonical=True), transaction.atomic(durable=True):
        get_or_create_team_extension(project, MCPIntentWriteBarrier)
        yield MCPIntentWriteBarrier.objects.select_for_update().get(team_id=project.pk)


def _freeze(barrier: MCPIntentWriteBarrier, invalidation_id: UUID) -> None:
    barrier.invalidation_id = invalidation_id
    barrier.frozen_at = timezone.now()
    barrier.generation += 1
    barrier.save(update_fields=["invalidation_id", "frozen_at", "generation"])


@contextmanager
def admit_writer(team: Team) -> Iterator[None]:
    """Register the run inside this transaction; begin remote work only after it commits."""
    with _locked_barrier(team) as barrier:
        if barrier.invalidation_id is not None:
            raise IntentWritesFrozen("Intent topic writes are frozen for this project")
        yield


def freeze_writes(team: Team, *, invalidation_id: UUID) -> None:
    with _locked_barrier(team) as barrier:
        if barrier.invalidation_id is not None and barrier.invalidation_id != invalidation_id:
            raise IntentInvalidationConflict("Another intent invalidation owns this project")
        if barrier.invalidation_id is None:
            _freeze(barrier, invalidation_id)


def snapshot_barrier(team: Team) -> BarrierSnapshot:
    """Capture the barrier before reading sources, to fence a later cache or digest fill."""
    project = team.parent_team or team
    with team_scope(project.pk, canonical=True):
        barrier = MCPIntentWriteBarrier.objects.filter(team_id=project.pk).first()
    if barrier is None:
        return BarrierSnapshot(generation=0, frozen=False)
    return BarrierSnapshot(generation=barrier.generation, frozen=barrier.invalidation_id is not None)


@contextmanager
def locked_fill(team: Team, snapshot: BarrierSnapshot) -> Iterator[None]:
    """Hold the barrier row lock while a derived result is written.

    Rejects the write when an erasure froze the barrier, or froze and reopened it, since the
    snapshot was taken. The generation survives reopen, so a delayed fill cannot slip through.
    """
    if snapshot.frozen:
        raise IntentWritesFrozen("The snapshot was captured while intent writes were frozen")
    with _locked_barrier(team) as barrier:
        if barrier.invalidation_id is not None or barrier.generation != snapshot.generation:
            raise IntentWritesFrozen("An intent erasure ran after this result was computed")
        yield


def has_pending_registered_writers(team: Team, *, invalidation_id: UUID) -> bool:
    """A zero excludes neither legacy producers nor queued output; it is not proof of erasure."""
    with _locked_barrier(team) as barrier:
        if barrier.invalidation_id != invalidation_id:
            raise IntentInvalidationConflict("This invalidation does not own the project's write barrier")
        # Failures, timeouts and old registrations can still have remote writes in flight. They do not expire.
        return MCPIntentClusteringRun.objects.filter(
            team_id=barrier.team_id,
            writer_registered_at__isnull=False,
            writer_completed_at__isnull=True,
        ).exists()
