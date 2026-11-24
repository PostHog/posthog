"""The org team roster, from the synced membership snapshot.

The read does not go through ``CuratedGitHubSource``, because that handle requires ``pull_requests``
and ``workflow_runs``, which a roster-only source may not sync.
"""

from typing import TYPE_CHECKING

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import GitHubTeamMembership, GitHubTeamRoster
from products.engineering_analytics.backend.logic.sources import resolve_team_membership_table
from products.engineering_analytics.backend.logic.views import team_members

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

_ROSTER_ROW_LIMIT = 100_000


def build_github_team_roster(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> GitHubTeamRoster:
    snapshot = resolve_team_membership_table(team=team, user_access_control=user_access_control)
    if snapshot is None:
        return GitHubTeamRoster(memberships=(), synced=False)

    roster_sql = team_members.build_roster_query(snapshot.table, has_role=snapshot.has_role)
    sql = f"SELECT * FROM ({roster_sql}) AS roster ORDER BY team_slug, member_handle LIMIT {_ROSTER_ROW_LIMIT}"
    with tags_context(product=Product.ENGINEERING_ANALYTICS, feature=Feature.QUERY, team_id=team.pk):
        response = execute_hogql_query(
            query=parse_select(sql),
            team=team,
            query_type="engineering_analytics.github_team_roster",
            # A userless caller has no ACL to honor, and HogQL would otherwise deny every warehouse table.
            user=user_access_control.user if user_access_control is not None else None,
            user_access_control=user_access_control,
            bypass_warehouse_access_control=user_access_control is None,
        )
    return GitHubTeamRoster(
        memberships=tuple(
            GitHubTeamMembership(
                member_handle=str(member_handle),
                team_slug=str(team_slug),
                team_name=str(team_name),
                is_maintainer=bool(is_maintainer),
            )
            for member_handle, team_slug, team_name, is_maintainer in (response.results or [])
        ),
        synced=True,
    )
