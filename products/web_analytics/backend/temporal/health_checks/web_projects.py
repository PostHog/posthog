from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models import Team

from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr


def teams_expecting_web_events(team_ids: list[int]) -> list[int]:
    """Teams that have sent a $pageview or $screen, or that have sent no event yet.

    A project that only sends other events, such as a backend or an MCP server, never sends web
    events, so a web check would flag it forever. Leaving it out of `detect` resolves what it holds.
    """
    teams = list(Team.objects.filter(id__in=team_ids).values_list("id", "project_id", "ingested_event"))
    web_project_ids = set(
        EventDefinition.objects.annotate(effective_project_id=effective_project_id_expr())
        .filter(
            effective_project_id__in={project_id for _, project_id, _ in teams},
            name__in=[PAGEVIEW_EVENT, SCREEN_EVENT],
            last_seen_at__isnull=False,
        )
        .values_list("effective_project_id", flat=True)
    )
    return [
        team_id for team_id, project_id, ingested_event in teams if not ingested_event or project_id in web_project_ids
    ]
