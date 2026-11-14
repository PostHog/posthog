from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team

from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentWriteBarrier


class IntentWritesFrozen(Exception):
    pass


class IntentInvalidationConflict(Exception):
    pass


@contextmanager
def _locked_barrier(team: Team) -> Iterator[MCPIntentWriteBarrier]:
    project = team.parent_team or team
    # Admission must commit before a caller reads sources or sends a remote write.
    with team_scope(project.pk, canonical=True), transaction.atomic(durable=True):
        get_or_create_team_extension(project, MCPIntentWriteBarrier)
        yield MCPIntentWriteBarrier.objects.select_for_update().get(team_id=project.pk)


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
            barrier.invalidation_id = invalidation_id
            barrier.frozen_at = timezone.now()
            barrier.save(update_fields=["invalidation_id", "frozen_at"])


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
