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
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

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
        coalesce(ci.pending, 0) AS pending
    FROM __PR_SOURCE__ AS pr
    LEFT JOIN ci_rollup AS ci ON ci.head_sha = pr.head_sha
    WHERE pr.state = 'open'
        OR pr.merged_at >= {{date_from}}
        OR pr.closed_at >= {{date_from}}
    ORDER BY pr.created_at DESC
    LIMIT {_LIMIT + 1}
"""


def query_pull_request_list(*, curated: CuratedGitHubSource, date_from: datetime) -> PullRequestList:
    response = curated.run(
        curated.pr_rollup_query(_SELECT),
        query_type="engineering_analytics.pull_request_list",
        placeholders={"date_from": ast.Constant(value=date_from)},
    )
    rows = response.results or []
    truncated = len(rows) > _LIMIT
    items = [_map_row(row) for row in rows[:_LIMIT]]
    return PullRequestList(items=items, truncated=truncated, limit=_LIMIT)


def _map_row(row: tuple) -> PullRequestListItem:
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
    ) = row
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
    )
