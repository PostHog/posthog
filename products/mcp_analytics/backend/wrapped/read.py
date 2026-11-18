from datetime import timedelta

from django.utils import timezone

from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.mcp_analytics.backend.facade.contracts import WrappedSnapshot
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped

# A wrap is a moment, not a report. It shows for this long after the job fills it, then the pop-up and the
# header button go away on their own until someone runs the job again.
DISPLAY_WINDOW = timedelta(days=14)


def get_fresh_wrapped(team: Team) -> WrappedSnapshot | None:
    with team_scope(team.id):
        snapshot = (
            MCPAnalyticsWrapped.objects.filter(
                team=team,
                status=MCPAnalyticsWrapped.Status.READY,
                generated_at__gte=timezone.now() - DISPLAY_WINDOW,
            )
            .order_by("-generated_at")
            .first()
        )
    if snapshot is None:
        return None
    return WrappedSnapshot(
        year=snapshot.year,
        generated_at=snapshot.generated_at,
        expires_at=snapshot.generated_at + DISPLAY_WINDOW,
        cards=snapshot.payload,
    )
