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
    PushCISample,
    RepoRef,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_list_costs

_LIMIT = 1000
# Sparkline cap: enough to read a PR's CI history at a glance without bloating a 1000-row page.
_PUSH_HISTORY_LIMIT = 20

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
        ci.failing_workflows AS failing_workflows,
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


# Per-push CI rounds for the visible PRs, for the push-history sparkline. Verdicts collapse like
# ``ci_rollup``: latest run per (push, workflow) via argMax, then any decisive failure turns the
# round red and any not-yet-completed run marks it pending. Wall time is the round's earliest run
# start to its latest completed run end (``updated_at`` is the end time the duration column uses).
#
# ``LIMIT __PUSH_HISTORY_LIMIT__ BY (repo_owner, repo_name, pr_number)`` bounds the scan to the most
# recent N pushes per PR *in ClickHouse* (rows are ordered newest-first, so the cap keeps the newest),
# rather than fetching every push and slicing in Python — a PR with hundreds of pushes never ships more
# than the sparkline shows. The trailing ``LIMIT`` is the overall ceiling (≤ 1000 PRs × N); without it
# HogQL applies its default 100-row limit and silently truncates the whole result.
_PUSH_HISTORY_SELECT = """
    SELECT
        repo_owner, repo_name, pr_number, head_sha,
        min(first_start) AS started_at,
        if(countIf(last_end IS NOT NULL) = 0, NULL, dateDiff('second', min(first_start), max(last_end))) AS wall_seconds,
        countIf(s = 'completed' AND c IN ('failure', 'timed_out')) > 0 AS failed,
        countIf(s IS NULL OR s != 'completed') > 0 AS pending
    FROM (
        SELECT
            repo_owner, repo_name, pr_number, head_sha, workflow_name,
            min(run_started_at) AS first_start,
            max(if(status = 'completed', updated_at, NULL)) AS last_end,
            argMax(status, run_started_at) AS s,
            argMax(conclusion, run_started_at) AS c
        FROM __RUNS_SOURCE__ AS r
        WHERE pr_number IN {pr_numbers}
        GROUP BY repo_owner, repo_name, pr_number, head_sha, workflow_name
    )
    GROUP BY repo_owner, repo_name, pr_number, head_sha
    ORDER BY started_at DESC
    LIMIT __PUSH_HISTORY_LIMIT__ BY (repo_owner, repo_name, pr_number)
    LIMIT 100000
"""


def query_pr_push_history(
    *, curated: CuratedGitHubSource, pr_numbers: list[int]
) -> dict[tuple[str, str, int], list[PushCISample]]:
    """Per-PR push rounds keyed by (repo_owner, repo_name, pr_number), oldest first, capped in
    ClickHouse to the most recent ``_PUSH_HISTORY_LIMIT`` per PR. Scoped to the visible PR numbers so
    the scan tracks the page (same shape as ``query_pr_list_costs``)."""
    if not pr_numbers:
        return {}
    sql = _PUSH_HISTORY_SELECT.replace("__RUNS_SOURCE__", curated.run_source()).replace(
        "__PUSH_HISTORY_LIMIT__", str(_PUSH_HISTORY_LIMIT)
    )
    response = curated.run(
        sql,
        query_type="engineering_analytics.pr_push_history",
        placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
    )
    by_pr: dict[tuple[str, str, int], list[PushCISample]] = {}
    for repo_owner, repo_name, pr_number, head_sha, started_at, wall_seconds, failed, pending in response.results or []:
        by_pr.setdefault((repo_owner, repo_name, int(pr_number)), []).append(
            PushCISample(
                head_sha=head_sha,
                started_at=started_at,
                wall_seconds=int(wall_seconds) if wall_seconds is not None else None,
                failed=bool(failed),
                pending=bool(pending),
            )
        )
    # The query returns newest-first (so the per-PR cap keeps the newest pushes); the contract is
    # oldest-first, so reverse each PR's list back to chronological order.
    return {key: samples[::-1] for key, samples in by_pr.items()}


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
    # Scope the cost and push-history rollups to exactly the PRs we're about to show (row[0] is
    # pr.number), so the scans track the page instead of the team's whole CI history.
    pr_numbers = sorted({int(row[0]) for row in visible})
    cost_by_pr = query_pr_list_costs(curated=curated, pr_numbers=pr_numbers)
    pushes_by_pr = query_pr_push_history(curated=curated, pr_numbers=pr_numbers)
    items = [_map_row(row, cost_by_pr, pushes_by_pr) for row in visible]
    return PullRequestList(items=items, truncated=truncated, limit=_LIMIT)


def _map_row(
    row: tuple,
    cost_by_pr: dict[tuple[str, str, int], PRCostAggregate],
    pushes_by_pr: dict[tuple[str, str, int], list[PushCISample]],
) -> PullRequestListItem:
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
        failing_workflows,
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
        # A PR with no CI misses the LEFT JOIN; the array column then comes back empty or NULL
        # depending on join_use_nulls — normalize both to [].
        ci=CIStatusRollup(
            runs=runs,
            passing=passing,
            failing=failing,
            pending=pending,
            failing_workflows=list(failing_workflows or []),
        ),
        pushes=pushes,
        rerun_cycles=rerun_cycles,
        estimated_cost_usd=cost.estimated_cost_usd if cost else None,
        billable_minutes=(cost.billable_seconds / 60) if cost else None,
        push_history=pushes_by_pr.get((repo_owner, repo_name, number), []),
    )
