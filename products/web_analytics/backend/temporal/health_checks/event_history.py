from collections.abc import Collection

from django.db.models import BigIntegerField, F
from django.db.models.functions import Coalesce

from posthog.models import EventDefinition, Team


def teams_that_ever_received(team_ids: Collection[int], events: Collection[str]) -> set[int]:
    if not team_ids:
        return set()
    project_by_team = dict(Team.objects.filter(id__in=team_ids).values_list("id", "project_id"))
    # Definitions are per project, and older rows have no project_id. This expression must match the
    # leading column of the event definition unique index, or the lookup stops using it.
    effective_project_id = Coalesce(F("project_id"), F("team_id"), output_field=BigIntegerField())
    projects_with_events = set(
        EventDefinition.objects.annotate(effective_project_id=effective_project_id)
        .filter(effective_project_id__in=set(project_by_team.values()), name__in=events)
        .values_list("effective_project_id", flat=True)
    )
    return {team_id for team_id, project_id in project_by_team.items() if project_id in projects_with_events}
