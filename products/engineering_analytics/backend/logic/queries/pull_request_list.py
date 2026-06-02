"""Curated query: PR list with head-SHA CI rollup.

All open PRs plus any merged or closed since ``date_from`` (the recency floor for
finished work; open PRs are always included regardless of age). Ordered newest
first, capped at ``_LIMIT``.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    CIStatusRollup,
    PRState,
    PullRequestListItem,
    RepoRef,
)
from products.engineering_analytics.backend.logic.queries import _curated

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
    LIMIT {_LIMIT}
"""


def query_pull_request_list(*, team: Team, date_from: datetime) -> list[PullRequestListItem]:
    sql = f"WITH {_curated.ci_rollup_cte()} {_SELECT}".replace("__PR_SOURCE__", _curated.pr_source())
    response = _curated.run_query(
        sql,
        team=team,
        query_type="engineering_analytics.pull_request_list",
        placeholders={"date_from": ast.Constant(value=date_from)},
    )
    return [_map_row(row) for row in response.results]


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
