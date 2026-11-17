from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import uuid4

from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

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
def registered_intent_writer(team: Team, *, purpose: str) -> Iterator[None]:
    """Enter before source reads; leave only after all writes and child work have joined.

    A failed or cancelled caller can leave remote writes in flight, so its registration
    remains pending until those writes are reconciled. It must never expire by age.
    """
    run = _register_writer(team, purpose=purpose)
    yield
    _complete_writer(run)


@asynccontextmanager
async def registered_intent_writer_async(team: Team, *, purpose: str) -> AsyncIterator[None]:
    run = await database_sync_to_async(_register_writer)(team, purpose=purpose)
    yield
    await database_sync_to_async(_complete_writer)(run)
