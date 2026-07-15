"""Curated query: a team's daily time-to-merge trend via GitHub org team membership.

Attributes merged PRs to a team through the ``team_members`` warehouse snapshot (PR author
login → GitHub team slug) — the one sanctioned place member data feeds a team surface. Only
team-level medians leave this module: no per-member figures, no cross-team rankings (SPEC
§2/§7). Bots are excluded per the default bot rule, and the repo-wide median over the same
window rides along as the comparison baseline, so the team line always answers "compared
to what?".

The GitHub team slug and the ownership-map slug (``test.owner_team``) are two namespaces
matched by exact slug. A team whose GitHub slug differs from its ownership slug gets no
membership rows (an empty team series with the baseline still drawn) — never another
team's data. Time-to-merge is the coarse ``open_to_merge_seconds`` (SPEC §7).
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import TeamMergeTrend, TeamMergeTrendPoint
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float

_SELECT = """
    SELECT
        toStartOfDay(pr.merged_at) AS day,
        medianIf(pr.open_to_merge_seconds, pr.author_handle IN (SELECT member_handle FROM members)) AS team_median_seconds,
        countIf(pr.author_handle IN (SELECT member_handle FROM members)) AS team_merged_count,
        median(pr.open_to_merge_seconds) AS repo_median_seconds,
        count() AS repo_merged_count
    FROM __PR_SOURCE__ AS pr
    WHERE pr.merged_at IS NOT NULL
        AND pr.merged_at >= {date_from}
        AND pr.merged_at <= {date_to}
        AND NOT pr.is_bot
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
        # The membership snapshot isn't synced — there is no honest team attribution, so return
        # the flag instead of a baseline-only chart that implies the team line is empty.
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
                team_median_seconds=opt_float(team_median_seconds),
                team_merged_count=team_merged_count,
                repo_median_seconds=opt_float(repo_median_seconds),
                repo_merged_count=repo_merged_count,
            )
            for (day, team_median_seconds, team_merged_count, repo_median_seconds, repo_merged_count) in (
                response.results or []
            )
        ],
    )
