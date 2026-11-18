"""Merged-PR counts per team for a window and the window before it, attributed through the
``team_members`` snapshot. A member of several teams credits each of them."""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.logic._shared import WindowedCount
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import UNPAGED_SCAN_LIMIT

_SELECT = f"""
    SELECT
        members.team_slug AS owner_team,
        countIf(pr.merged_at >= {{date_from}}) AS merged_pr_count,
        countIf(pr.merged_at < {{date_from}}) AS merged_pr_count_prior
    FROM __PR_SOURCE__ AS pr
    JOIN __MEMBERS_SOURCE__ AS members ON pr.author_handle = members.member_handle
    WHERE pr.merged_at IS NOT NULL
        AND pr.merged_at >= {{scan_from}}
        AND pr.merged_at <= {{date_to}}
        AND NOT pr.is_bot
    GROUP BY owner_team
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


def query_team_merged_pr_counts(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    scan_from: datetime,
    date_to: datetime,
) -> dict[str, WindowedCount] | None:
    """Counts keyed by team slug. Returns None when the membership snapshot is not synced, which
    callers must not report as zero merges."""
    members_source = curated.members_source()
    if members_source is None:
        return None
    sql = _SELECT.replace("__PR_SOURCE__", curated.pr_source()).replace("__MEMBERS_SOURCE__", members_source)
    response = curated.run(
        sql,
        query_type="engineering_analytics.team_merged_pr_counts",
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "scan_from": ast.Constant(value=scan_from),
            "date_to": ast.Constant(value=date_to),
        },
    )
    return {
        owner_team: WindowedCount(current=int(count), prior=int(prior))
        for owner_team, count, prior in (response.results or [])
    }
