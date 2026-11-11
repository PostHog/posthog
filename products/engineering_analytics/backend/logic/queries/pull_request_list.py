"""Curated query: PR list with head-SHA CI rollup.

All open PRs plus any merged or closed since ``date_from`` (the recency floor for
finished work; open PRs are always included regardless of age). Ordered newest
first, capped at ``_LIMIT``. The query fetches ``_LIMIT + 1`` rows so an overflow is
detectable, and the result reports ``truncated`` rather than silently dropping the
tail (the aggregate counts in ``ci_cards`` can then legitimately exceed the list).

A ``state`` narrows the list to one state and orders it by that state's own timestamp
(``merged_at`` for merged, ``closed_at`` for closed), so the cap covers only those rows.
Every ordering ends on the PR key, so ``limit`` / ``offset`` pages never skip or repeat
a row when two PRs share a timestamp.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import (
    AttentionPullRequestList,
    Author,
    CIStatusRollup,
    PRState,
    PullRequestList,
    PullRequestListItem,
    PushCISample,
    RepoRef,
)
from products.engineering_analytics.backend.logic.cost import PRCostAggregate
from products.engineering_analytics.backend.logic.queries._curated import (
    READY_TO_MERGE_UNOBSERVABLE,
    CuratedGitHubSource,
    ReadyToMergeSql,
)
from products.engineering_analytics.backend.logic.queries._workflow_filters import DECISIVE_FAILURE_CONCLUSIONS_SQL
from products.engineering_analytics.backend.logic.queries.ci_cards import FAILING_CI_SQL, OPEN_PR_SQL, stuck_pr_sql
from products.engineering_analytics.backend.logic.queries.pr_cost import PullRequestKey, query_pr_costs

_LIMIT = 1000
_ATTENTION_LIMIT = 15
# Sparkline cap: enough to read a PR's CI history at a glance without bloating a 1000-row page.
_PUSH_HISTORY_LIMIT = 20


def _visible_prs_where(prefix: str, author: str | None, state: PRState | None, has_date_to: bool) -> str:
    """The list's row predicate, buildable against the ``pr`` alias (outer WHERE) or
    unqualified curated PR columns (the runs-rollup scope) — one definition so the
    rollup scope can never drift narrower than the rows it must serve."""

    def in_window(column: str) -> str:
        upper = f" AND {prefix}{column} < {{date_to}}" if has_date_to else ""
        return f"({prefix}{column} >= {{date_from}}{upper})"

    author_clause = f"AND {prefix}author_handle = {{author}}" if author else ""
    if state == PRState.OPEN:
        state_clause = f"{prefix}state = 'open'"
    elif state == PRState.MERGED:
        state_clause = f"{prefix}state = 'merged' AND {in_window('merged_at')}"
    elif state == PRState.CLOSED:
        state_clause = f"{prefix}state = 'closed' AND {in_window('closed_at')}"
    else:
        state_clause = f"{prefix}state = 'open' OR {in_window('merged_at')} OR {in_window('closed_at')}"
    return f"({state_clause}) {author_clause}"


_ORDER_COLUMN_BY_STATE = {PRState.MERGED: "merged_at", PRState.CLOSED: "closed_at"}


def _order_by(state: PRState | None) -> str:
    timestamp = _ORDER_COLUMN_BY_STATE.get(state, "created_at") if state else "created_at"
    return f"pr.{timestamp} DESC, pr.number DESC, pr.repo_owner, pr.repo_name"


_SELECT = """
    SELECT
        pr.number, pr.title, pr.repo_owner, pr.repo_name,
        pr.author_handle, pr.author_avatar_url, pr.is_bot,
        pr.state, pr.is_draft, pr.created_at, pr.merged_at,
        pr.open_to_merge_seconds,
        __READY_TO_MERGE__,
        pr.labels,
        coalesce(ci.runs, 0) AS runs,
        coalesce(ci.passing, 0) AS passing,
        coalesce(ci.failing, 0) AS failing,
        coalesce(ci.pending, 0) AS pending,
        coalesce(ci.inconclusive, 0) AS inconclusive,
        ci.failing_workflows AS failing_workflows
        __EXTRA_COLUMNS__
    FROM __PR_SOURCE__ AS pr
    LEFT JOIN ci_rollup AS ci ON ci.head_sha = pr.head_sha
    __READY_JOIN__
    WHERE __ROWS__
    ORDER BY __ORDER_BY__
    LIMIT __LIMIT__ OFFSET __OFFSET__
"""


# Per-push CI rounds for the visible PRs, for the push-history sparkline, plus each PR's ``pushes`` and
# ``rerun_cycles``. Verdicts collapse like ``ci_rollup``: latest run per (push, workflow) via argMax,
# then any decisive failure turns the round red and any not-yet-completed run marks it pending. Wall
# time is the round's earliest run start to its latest completed run end (``updated_at`` is the end
# time the duration column uses).
#
# Merge-queue gate runs are excluded. A gate branch's head SHA is a rebase the queue made, not a push
# the author made. Gate runs are also a PR's newest rounds, so they would push the author's real pushes
# out of the capped window below.
#
# ``LIMIT __PUSH_HISTORY_LIMIT__ BY (repo_owner, repo_name, pr_number)`` bounds the scan to the most
# recent N pushes per PR *in ClickHouse* (rows are ordered newest-first, so the cap keeps the newest),
# rather than fetching every push and slicing in Python — a PR with hundreds of pushes never ships more
# than the sparkline shows. The window functions run before ``LIMIT BY``, so ``pushes`` and
# ``rerun_cycles`` count every push. The trailing ``LIMIT`` is the overall ceiling (≤ 1000 PRs × N);
# without it HogQL applies its default 100-row limit and silently truncates the whole result.
_PUSH_ACTIVITY_SELECT = """
    SELECT
        repo_owner, repo_name, pr_number, head_sha, started_at, wall_seconds, failed, pending,
        countIf(head_sha IS NOT NULL) OVER (PARTITION BY repo_owner, repo_name, pr_number) AS pushes,
        sum(rerun_runs) OVER (PARTITION BY repo_owner, repo_name, pr_number) AS rerun_cycles
    FROM (
        SELECT
            repo_owner, repo_name, pr_number, head_sha,
            min(first_start) AS started_at,
            if(countIf(last_end IS NOT NULL) = 0, NULL, dateDiff('second', min(first_start), max(last_end))) AS wall_seconds,
            countIf(s = 'completed' AND c IN (__DECISIVE_FAILURES__)) > 0 AS failed,
            countIf(s IS NULL OR s != 'completed') > 0 AS pending,
            sum(rerun_runs) AS rerun_runs
        FROM (
            SELECT
                repo_owner, repo_name, pr_number, head_sha, workflow_name,
                min(run_started_at) AS first_start,
                max(if(status = 'completed', updated_at, NULL)) AS last_end,
                argMax(status, run_started_at) AS s,
                argMax(conclusion, run_started_at) AS c,
                countIf(run_attempt > 1) AS rerun_runs
            FROM __RUNS_SOURCE__ AS r
            WHERE pr_number IN {pr_numbers} AND NOT is_merge_queue
            GROUP BY repo_owner, repo_name, pr_number, head_sha, workflow_name
        )
        GROUP BY repo_owner, repo_name, pr_number, head_sha
    )
    ORDER BY started_at DESC
    LIMIT __PUSH_HISTORY_LIMIT__ BY (repo_owner, repo_name, pr_number)
    LIMIT 100000
"""


@frozen
class PushActivity:
    pushes: int
    rerun_cycles: int
    # Oldest first and capped to the most recent ``_PUSH_HISTORY_LIMIT`` pushes, while ``pushes`` counts every push.
    history: list[PushCISample]


def query_pr_push_activity(
    *, curated: CuratedGitHubSource, pr_numbers: list[int]
) -> dict[PullRequestKey, PushActivity]:
    """Per-PR push activity keyed by (repo_owner, repo_name, pr_number). Scoped to the visible PR
    numbers so the scan tracks the page (same shape as ``query_pr_costs``). A PR with no CI has no entry."""
    if not pr_numbers:
        return {}
    sql = (
        _PUSH_ACTIVITY_SELECT.replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__PUSH_HISTORY_LIMIT__", str(_PUSH_HISTORY_LIMIT))
        .replace("__DECISIVE_FAILURES__", DECISIVE_FAILURE_CONCLUSIONS_SQL)
    )
    response = curated.run(
        sql,
        query_type="engineering_analytics.pr_push_history",
        placeholders={"pr_numbers": ast.Constant(value=pr_numbers)},
    )
    activity: dict[PullRequestKey, PushActivity] = {}
    for (
        repo_owner,
        repo_name,
        pr_number,
        head_sha,
        started_at,
        wall_seconds,
        failed,
        pending,
        pushes,
        rerun_cycles,
    ) in response.results or []:
        key = (repo_owner, repo_name, int(pr_number))
        pr_activity = activity.setdefault(
            key, PushActivity(pushes=int(pushes), rerun_cycles=int(rerun_cycles or 0), history=[])
        )
        pr_activity.history.append(
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
    for pr_activity in activity.values():
        pr_activity.history.reverse()
    return activity


def _query_rows(
    *,
    curated: CuratedGitHubSource,
    scope_where: str,
    rows_where: str,
    order_by: str,
    limit: int,
    offset: int = 0,
    query_type: str,
    placeholders: dict[str, ast.Expr],
    ready: ReadyToMergeSql,
    extra_columns: str = "",
) -> list[tuple]:
    """``scope_where`` is over unqualified curated PR columns and must keep every row ``rows_where``
    keeps, because it prunes the CI rollup (see ``pr_rollup_query``)."""
    select = (
        _SELECT.replace("__READY_TO_MERGE__", f"{ready.expr} AS ready_to_merge_seconds")
        .replace("__READY_JOIN__", ready.join)
        .replace("__EXTRA_COLUMNS__", extra_columns)
        .replace("__ROWS__", rows_where)
        .replace("__ORDER_BY__", order_by)
        .replace("__LIMIT__", str(limit))
        .replace("__OFFSET__", str(offset))
    )
    response = curated.run(
        curated.pr_rollup_query(select, pr_scope_where=scope_where, ready=ready),
        query_type=query_type,
        placeholders=placeholders,
    )
    return list(response.results or [])


def _enrich(*, curated: CuratedGitHubSource, rows: list[tuple]) -> list[PullRequestListItem]:
    # Scope the cost and push-history rollups to exactly the PRs we're about to show (row[0] is
    # pr.number), so the scans track the page instead of the team's whole CI history.
    pr_numbers = sorted({int(row[0]) for row in rows})
    with curated.concurrent_reads() as reads:
        costs_read = reads.submit(lambda: query_pr_costs(curated=curated, pr_numbers=pr_numbers))
        activity_read = reads.submit(lambda: query_pr_push_activity(curated=curated, pr_numbers=pr_numbers))
    cost_by_pr, activity_by_pr = costs_read.result(), activity_read.result()
    return [_map_row(row, cost_by_pr, activity_by_pr) for row in rows]


def query_pull_request_list(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None = None,
    author: str | None = None,
    state: PRState | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> PullRequestList:
    page_size = _LIMIT if limit is None else limit
    if not 1 <= page_size <= _LIMIT:
        raise ValueError(f"limit must be between 1 and {_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be zero or greater")

    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    if author:
        placeholders["author"] = ast.Constant(value=author)
    rows = _query_rows(
        curated=curated,
        scope_where=_visible_prs_where("", author, state, date_to is not None),
        rows_where=_visible_prs_where("pr.", author, state, date_to is not None),
        order_by=_order_by(state),
        limit=page_size + 1,
        offset=offset,
        query_type="engineering_analytics.pull_request_list",
        placeholders=placeholders,
        ready=curated.ready_to_merge_sql(),
    )
    return PullRequestList(
        items=_enrich(curated=curated, rows=rows[:page_size]), truncated=len(rows) > page_size, limit=page_size
    )


def query_attention_pull_requests(*, curated: CuratedGitHubSource) -> AttentionPullRequestList:
    rows = _query_rows(
        curated=curated,
        scope_where=OPEN_PR_SQL,
        rows_where=f"pr.{OPEN_PR_SQL} AND ({FAILING_CI_SQL} OR {stuck_pr_sql('pr.')})",
        order_by=f"{FAILING_CI_SQL} DESC, pr.created_at DESC, pr.repo_owner, pr.repo_name, pr.number DESC",
        limit=_ATTENTION_LIMIT,
        query_type="engineering_analytics.attention_pull_requests",
        placeholders={},
        # An open pull request has no ready-to-merge time, so the issue-events scans would add nothing.
        ready=READY_TO_MERGE_UNOBSERVABLE,
        extra_columns=", count() OVER () AS matching",
    )
    return AttentionPullRequestList(
        items=_enrich(curated=curated, rows=[row[:-1] for row in rows]),
        total=int(rows[0][-1]) if rows else 0,
        limit=_ATTENTION_LIMIT,
    )


def _map_row(
    row: tuple,
    cost_by_pr: dict[PullRequestKey, PRCostAggregate],
    activity_by_pr: dict[PullRequestKey, PushActivity],
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
        ready_to_merge_seconds,
        labels,
        runs,
        passing,
        failing,
        pending,
        inconclusive,
        failing_workflows,
    ) = row
    cost = cost_by_pr.get((repo_owner, repo_name, number))
    activity = activity_by_pr.get((repo_owner, repo_name, number))
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
        ready_to_merge_seconds=int(ready_to_merge_seconds) if ready_to_merge_seconds is not None else None,
        labels=list(labels),
        # A PR with no CI misses the LEFT JOIN; the array column then comes back empty or NULL
        # depending on join_use_nulls — normalize both to [].
        ci=CIStatusRollup(
            runs=runs,
            passing=passing,
            failing=failing,
            pending=pending,
            inconclusive=inconclusive,
            failing_workflows=list(failing_workflows or []),
        ),
        pushes=activity.pushes if activity else 0,
        rerun_cycles=activity.rerun_cycles if activity else 0,
        estimated_cost_usd=cost.estimated_cost_usd if cost else None,
        billable_minutes=(cost.billable_seconds / 60) if cost else None,
        push_history=activity.history if activity else [],
    )
