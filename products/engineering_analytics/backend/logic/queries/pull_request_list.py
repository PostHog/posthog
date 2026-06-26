"""Curated query: PR list with head-SHA CI rollup.

All open PRs plus any merged or closed since ``date_from`` (the recency floor for
finished work; open PRs are always included regardless of age). Ordered newest
first, capped at ``_LIMIT``. The query fetches ``_LIMIT + 1`` rows so an overflow is
detectable, and the result reports ``truncated`` rather than silently dropping the
tail (the aggregate counts in ``ci_cards`` can then legitimately exceed the list).
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    CIStatusRollup,
    PRState,
    PullRequestList,
    PullRequestListItem,
    RepoRef,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_list_costs

_LIMIT = 1000

_SELECT = f"""
    SELECT
        pr.number, pr.title, pr.repo_owner, pr.repo_name,
        pr.author_handle, pr.author_avatar_url, pr.is_bot,
        pr.state, pr.is_draft, pr.created_at, pr.merged_at,
        pr.open_to_merge_seconds, pr.labels,
        coalesce(ci.runs, 0) AS runs,
        coalesce(ci.passing, 0) AS passing,
        coalesce(ci.failing, 0) AS failing,
        coalesce(ci.pending, 0) AS pending,
        coalesce(rp.pushes, 0) AS pushes,
        coalesce(rp.rerun_cycles, 0) AS rerun_cycles
    FROM __PR_SOURCE__ AS pr
    LEFT JOIN ci_rollup AS ci ON ci.head_sha = pr.head_sha
    LEFT JOIN runs_by_pr AS rp
        ON rp.repo_owner = pr.repo_owner AND rp.repo_name = pr.repo_name AND rp.pr_number = pr.number
    WHERE (
            pr.state = 'open'
            OR pr.merged_at >= {{date_from}}
            OR pr.closed_at >= {{date_from}}
        ) __AUTHOR__
    ORDER BY pr.created_at DESC
    LIMIT {_LIMIT + 1}
"""


def query_pull_request_list(
    *, curated: CuratedGitHubSource, date_from: datetime, author: str | None = None
) -> PullRequestList:
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    author_clause = ""
    if author:
        author_clause = "AND pr.author_handle = {author}"
        placeholders["author"] = ast.Constant(value=author)
    response = curated.run(
        curated.pr_list_rollup_query(_SELECT.replace("__AUTHOR__", author_clause)),
        query_type="engineering_analytics.pull_request_list",
        placeholders=placeholders,
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    visible = rows[:_LIMIT]
    # Scope the cost rollup to exactly the PRs we're about to show (row[0] is pr.number), so the
    # jobs×runs join tracks the page instead of scanning the team's whole CI history.
    pr_numbers = sorted({int(row[0]) for row in visible})
    cost_by_pr = query_pr_list_costs(curated=curated, pr_numbers=pr_numbers)
    items = [_map_row(row, cost_by_pr) for row in visible]
    return PullRequestList(items=items, truncated=truncated, limit=_LIMIT)


def _map_row(row: tuple, cost_by_pr: dict[tuple[str, str, int], PRCostAggregate]) -> PullRequestListItem:
    (
        number,
        title,
        repo_owner,
        repo_name,
        author_handle,
        author_avatar_url,
        is_bot,
        state,
        is_draft,
        created_at,
        merged_at,
        open_to_merge_seconds,
        labels,
        runs,
        passing,
        failing,
        pending,
        pushes,
        rerun_cycles,
    ) = row
    cost = cost_by_pr.get((repo_owner, repo_name, number))
    return PullRequestListItem(
        number=number,
        title=title,
        author=Author(
            handle=author_handle,
            display_name=author_handle,
            avatar_url=author_avatar_url,
            is_bot=bool(is_bot),
        ),
        repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
        state=PRState(state),
        is_draft=bool(is_draft),
        created_at=created_at,
        merged_at=merged_at,
        open_to_merge_seconds=open_to_merge_seconds,
        labels=list(labels),
        ci=CIStatusRollup(runs=runs, passing=passing, failing=failing, pending=pending),
        pushes=pushes,
        rerun_cycles=rerun_cycles,
        estimated_cost_usd=cost.estimated_cost_usd if cost else None,
        billable_minutes=(cost.billable_seconds / 60) if cost else None,
    )
