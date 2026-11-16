from collections.abc import Iterable
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from posthog.models.team.team import Team
from posthog.taxonomy.taxonomy import STALE_EVENT_DAYS

from products.event_definitions.backend.models import EventDefinition


def recently_seen_event_names(team: Team, names: Iterable[str]) -> set[str]:
    """The given event names that the project ingested within the stale-event window.

    Matches the event definitions API with `exclude_stale`, minus the definitions that were never seen.
    """
    return set(
        EventDefinition.objects.filter(
            Q(project_id=team.project_id) | Q(project_id__isnull=True, team_id=team.id),
            name__in=list(names),
            last_seen_at__gt=timezone.now() - timedelta(days=STALE_EVENT_DAYS),
        ).values_list("name", flat=True)
    )
