"""Curated query: a team's daily time-to-merge trend via GitHub org team membership.

Attributes merged PRs to a team through the ``team_members`` warehouse snapshot (PR author
login → GitHub team slug), the one sanctioned place member data feeds a team surface. Only
team-level aggregates leave this module (the daily median and average of the team's own
merges): no per-member figures, no cross-team rankings (SPEC §2/§7). Bots are excluded per
the default bot rule.

The GitHub team slug and the ownership-map slug (``test.owner_team``) are two namespaces
matched by exact slug. A team whose GitHub slug differs from its ownership slug gets no
membership rows (an empty series), never another team's data. Time-to-merge is the coarse
``open_to_merge_seconds`` (SPEC §7).
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import TeamMergeTrend, TeamMergeTrendPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float

_SELECT = """
    SELECT
        toStartOfDay(pr.merged_at) AS day,
        median(pr.open_to_merge_seconds) AS median_seconds,
        avg(pr.open_to_merge_seconds) AS average_seconds,
        count() AS merged_count
    FROM __PR_SOURCE__ AS pr
    WHERE pr.merged_at IS NOT NULL
        AND pr.merged_at >= {date_from}
        AND pr.merged_at <= {date_to}
        AND NOT pr.is_bot
        AND pr.author_handle IN (SELECT member_handle FROM members)
    GROUP BY day
    ORDER BY day ASC
"""


def query_team_merge_trend(
    *,
    curated: CuratedGitHubSource,
    owner_team: str,
    date_from: datetime,
    date_to: datetime | None,
) -> TeamMergeTrend:
    members_source = curated.members_source()
    if members_source is None:
        # The membership snapshot isn't synced, so there is no honest team attribution: return
        # the flag instead of an empty series that implies the team merged nothing.
        return TeamMergeTrend(owner_team=owner_team, has_membership_data=False, points=[])

    sql = f"WITH members AS (SELECT member_handle FROM {members_source} WHERE team_slug = {{owner_team}}) {_SELECT}"
    response = curated.run(
        sql.replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.team_merge_trend",
        placeholders={
            "owner_team": ast.Constant(value=owner_team),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to or datetime.now(tz=date_from.tzinfo)),
        },
    )
    return TeamMergeTrend(
        owner_team=owner_team,
        has_membership_data=True,
        points=[
            TeamMergeTrendPoint(
                day=day,
                median_seconds=opt_float(median_seconds),
                average_seconds=opt_float(average_seconds),
                merged_count=merged_count,
            )
            for (day, median_seconds, average_seconds, merged_count) in (response.results or [])
        ],
    )
