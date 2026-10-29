from itertools import batched

from posthog.dataclasses import frozen
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.db import filter_recently_active_teams
from posthog.temporal.health_checks.rollups.freshness import RollupWindow, window_rows

from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.temporal.health_checks.sdk_outdated import SdkOutdatedCheck

RESOLVE_BATCH_SIZE = 1000


@frozen
class StaleSdkIssues:
    active_issues: int
    no_sdk_traffic_team_ids: list[int]
    no_recent_login_team_ids: list[int]

    @property
    def team_ids(self) -> list[int]:
        return sorted({*self.no_sdk_traffic_team_ids, *self.no_recent_login_team_ids})


def find_stale_sdk_issues(window: RollupWindow) -> StaleSdkIssues:
    """Active sdk_outdated issues the scheduled check can no longer reach.

    The check only visits teams with a member login in the last `active_since_days`, and only
    resolves an SDK it saw traffic for. A team with no SDK traffic in the window, or whose members
    stopped logging in, keeps its issues forever.
    """
    issue_team_ids = list(
        HealthIssue.objects.filter(kind=SdkOutdatedCheck.kind, status=HealthIssue.Status.ACTIVE).values_list(
            "team_id", flat=True
        )
    )
    team_ids = set(issue_team_ids)

    teams_with_traffic: set[int] = set()
    for batch in batched(sorted(team_ids), RESOLVE_BATCH_SIZE, strict=False):
        teams_with_traffic.update(
            window_rows(SdkVersionsDaily, batch, window).values_list("team_id", flat=True).distinct()
        )

    recently_active = set(
        filter_recently_active_teams(
            Team.objects.filter(id__in=team_ids), SdkOutdatedCheck.active_since_days or 0
        ).values_list("id", flat=True)
    )

    return StaleSdkIssues(
        active_issues=len(issue_team_ids),
        no_sdk_traffic_team_ids=sorted(team_ids - teams_with_traffic),
        no_recent_login_team_ids=sorted(team_ids - recently_active),
    )


def resolve_sdk_issues_for_teams(team_ids: list[int]) -> int:
    """Resolve every active sdk_outdated issue of the given teams, without sending resolved alerts."""
    return sum(
        len(HealthIssue.bulk_resolve(SdkOutdatedCheck.kind, set(batch)))
        for batch in batched(team_ids, RESOLVE_BATCH_SIZE, strict=False)
    )
