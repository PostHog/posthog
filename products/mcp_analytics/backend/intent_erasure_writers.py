from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import uuid4

from django.utils import timezone

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.mcp_analytics.backend.facade.contracts import IntentErasure, IntentErasurePending
from products.mcp_analytics.backend.intent_topics.invalidation import admit_writer
from products.mcp_analytics.backend.models import MCPIntentClusteringRun


def _register_writer(team: Team, *, purpose: str) -> MCPIntentClusteringRun:
    with admit_writer(team):
        return MCPIntentClusteringRun.objects.create(
            team=team.parent_team or team,
            run_id=f"writer/{uuid4()}",
            kind="legacy",
            params={"source_team_id": team.pk, "purpose": purpose},
            writer_registered_at=timezone.now(),
        )


def _complete_writer(run: MCPIntentClusteringRun) -> None:
    with team_scope(run.team_id, canonical=True):
        updated = MCPIntentClusteringRun.objects.filter(pk=run.pk, team_id=run.team_id).update(
            status=MCPIntentClusteringRun.Status.SUCCEEDED,
            finished_at=timezone.now(),
            writer_completed_at=timezone.now(),
        )
        if updated != 1:
            raise RuntimeError("Intent writer registration disappeared before completion")


@contextmanager
def registered_intent_writer(
    team: Team, *, purpose: str, no_write_errors: tuple[type[Exception], ...] = ()
) -> Iterator[None]:
    """Enter before source reads; leave only after all writes and child work have joined.

    A failed or cancelled caller can leave remote writes in flight, so its registration
    remains pending until those writes are reconciled. It must never expire by age.
    ``no_write_errors`` names exceptions the caller raises only before any write is dispatched,
    such as a refused LLM call. Those complete the registration, so they cannot block erasure.
    """
    run = _register_writer(team, purpose=purpose)
    try:
        yield
    except no_write_errors:
        _complete_writer(run)
        raise
    _complete_writer(run)


@asynccontextmanager
async def registered_intent_writer_async(
    team: Team, *, purpose: str, no_write_errors: tuple[type[Exception], ...] = ()
) -> AsyncIterator[None]:
    run = await database_sync_to_async(_register_writer)(team, purpose=purpose)
    try:
        yield
    except no_write_errors:
        await database_sync_to_async(_complete_writer)(run)
        raise
    await database_sync_to_async(_complete_writer)(run)


def assert_writers_drained(*, erasure: IntentErasure, cluster: ClickhouseCluster) -> None:
    """Erasure provider: raise unless every intent writer in the project has confirmed its writes.

    The coordinator calls this while it holds the frozen barrier row, so it reads the runs directly
    instead of taking the barrier lock again. Writes here are synchronous, so the ClickHouse cluster
    is not needed to prove them.
    """
    for team_id in {erasure.project_id, *erasure.source_team_ids}:
        with team_scope(team_id, canonical=True):
            runs = MCPIntentClusteringRun.objects.filter(team_id=team_id)
            if runs.filter(writer_registered_at__isnull=False, writer_completed_at__isnull=True).exists():
                raise IntentErasurePending("An intent writer has not confirmed that its writes finished")
            # A run from before writer registration may have queued output that nothing tracked.
            if runs.filter(writer_registered_at__isnull=True).exists():
                raise IntentErasurePending("A run from before writer registration may still have queued output")
