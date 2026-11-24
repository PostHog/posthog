import dataclasses
from datetime import UTC, datetime

from django.db.models.functions import Coalesce

import structlog
from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.temporal.common.heartbeat import Heartbeater

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.wrapped.generate import generate_wrapped_snapshot

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class WrappedDiscoveryInputs:
    year: int


@dataclasses.dataclass(frozen=True)
class WrappedTeamInputs:
    team_id: int
    year: int


def wrapped_team_ids(year: int) -> list[int]:
    """Projects that sent a tool call this year, read from event definitions so no team's events are scanned.

    Each project still has to clear the eligibility bar when its snapshot is generated.
    """
    # A project keeps one definition per event, under the team of whichever environment sent the event first.
    # So the definition only names the project, and every root environment in it gets a wrap.
    project_ids = (
        EventDefinition.objects.filter(name=MCP_TOOL_CALL_EVENT, last_seen_at__gte=datetime(year, 1, 1, tzinfo=UTC))
        .values_list(Coalesce("project_id", "team__project_id"), flat=True)
        .distinct()
    )
    return sorted(
        Team.objects.filter(project_id__in=project_ids, parent_team__isnull=True).values_list("id", flat=True)
    )


@activity.defn
async def discover_wrapped_team_ids_activity(inputs: WrappedDiscoveryInputs) -> list[int]:
    async with Heartbeater():
        return await database_sync_to_async(wrapped_team_ids)(inputs.year)


def _generate(team_id: int, year: int) -> str:
    with team_scope(team_id):
        team = Team.objects.get(id=team_id)
        return generate_wrapped_snapshot(team, year).status


@activity.defn
async def generate_wrapped_activity(inputs: WrappedTeamInputs) -> str:
    async with Heartbeater():
        status = await database_sync_to_async_pool(_generate)(inputs.team_id, inputs.year)
    logger.info("mcpa.wrapped.team_generated", team_id=inputs.team_id, year=inputs.year, status=status)
    return status
