"""A team's daily time-to-merge (``open_to_merge_seconds``), attributed through the ``team_members`` snapshot.

Only team aggregates leave this module, never per-member figures (SPEC §2 and §6). ``owner_team``
must equal the GitHub team slug exactly, and a slug with no membership rows gives an empty series.
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
        # An empty series alone would imply the team merged nothing, so the flag says the snapshot is unsynced.
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
