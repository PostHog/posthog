from collections import defaultdict

from posthog.constants import PAGEVIEW_EVENT, SCREEN_EVENT
from posthog.models import Team

from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr

WEB_EVENTS = frozenset({PAGEVIEW_EVENT, SCREEN_EVENT})


def expected_web_events(team_ids: list[int]) -> dict[int, frozenset[str]]:
    """The web events each team is expected to send: the ones it has sent, or both when it has sent no event yet.

    A project that only sends other events, such as a backend or an MCP server, never sends web
    events, so a web check would flag it forever. Such a team is left out, and leaving it out of
    `detect` resolves what it holds. A mobile app sends $screen and no $pageview, so a check that
    only applies to websites reads $pageview from the result.
    """
    teams = list(Team.objects.filter(id__in=team_ids).values_list("id", "project_id", "ingested_event"))
    seen_by_project: defaultdict[int, set[str]] = defaultdict(set)
    for project_id, event in (
        EventDefinition.objects.annotate(effective_project_id=effective_project_id_expr())
        .filter(
            effective_project_id__in={project_id for _, project_id, _ in teams},
            name__in=WEB_EVENTS,
            last_seen_at__isnull=False,
        )
        .values_list("effective_project_id", "name")
    ):
        seen_by_project[project_id].add(event)
    expected = {
        team_id: WEB_EVENTS if not ingested_event else frozenset(seen_by_project[project_id])
        for team_id, project_id, ingested_event in teams
    }
    return {team_id: events for team_id, events in expected.items() if events}


def teams_expecting_pageviews(team_ids: list[int]) -> list[int]:
    return [team_id for team_id, events in expected_web_events(team_ids).items() if PAGEVIEW_EVENT in events]
