"""Curated query: repo-level headline aggregates for the repo hub landing page.

One runs scan covers the current window and the equal-length window before it, so
every headline number ships with its previous-window twin and the UI can render an
honest delta instead of a server-baked percentage. The PR medians (bots and drafts
excluded, per the locked cycle-time recipe) come from the PR snapshot the same way.

The default-branch health series buckets completed runs on the repo's default
branch ('master' vs 'main', picked by observed run volume) with the same
granularity ladder as workflow_health.
"""

import math
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import RepoOverview, RepoOverviewBucket
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_cost import query_workflow_window_costs
from products.engineering_analytics.backend.logic.queries.workflow_health import (
    _BUCKET_FN,
    _normalize,
    _pick_granularity,
    _window_buckets,
)

_RUNS_SELECT = """
    SELECT
        countIf(__CUR__) AS run_count,
        countIf(__PREV__) AS run_count_prev,
        countIf(status = 'completed' AND conclusion = 'success' AND __CUR__)
            / nullIf(countIf(status = 'completed' AND __CUR__), 0) AS success_rate,
        countIf(status = 'completed' AND conclusion = 'success' AND __PREV__)
            / nullIf(countIf(status = 'completed' AND __PREV__), 0) AS success_rate_prev,
        countIf(run_attempt > 1 AND __CUR__) AS rerun_cycles,
        countIf(run_attempt > 1 AND __PREV__) AS rerun_cycles_prev,
        countIf(head_branch = 'master' AND __CUR__) AS master_runs,
        countIf(head_branch = 'main' AND __CUR__) AS main_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {prev_from} __DATE_TO__
"""

_PR_SELECT = """
    SELECT
        quantileIf(0.5)(open_to_merge_seconds, __CUR_MERGED__ AND NOT is_bot AND NOT is_draft) AS median_cur,
        quantileIf(0.5)(open_to_merge_seconds, __PREV_MERGED__ AND NOT is_bot AND NOT is_draft) AS median_prev
    FROM __PR_SOURCE__ AS pr
    WHERE merged_at IS NOT NULL AND merged_at >= {prev_from}
"""

_BUCKET_SELECT = """
    SELECT
        __BUCKET_FN__ AS bucket_start,
        countIf(status = 'completed') AS completed,
        countIf(status = 'completed' AND conclusion = 'success') AS successes
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from} __DATE_TO__ AND head_branch = {default_branch}
    GROUP BY bucket_start
    LIMIT 400
"""


_DEFAULT_BRANCH_SELECT = """
    SELECT countIf(head_branch = 'master') AS master_runs, countIf(head_branch = 'main') AS main_runs
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {date_from} __DATE_TO__
"""


def query_default_branch(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> str:
    """'master' or 'main', by observed run volume in the window — the cheap standalone variant of the
    detection the overview aggregate gets for free."""
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    response = curated.run(
        _DEFAULT_BRANCH_SELECT.replace("__RUNS_SOURCE__", curated.run_source()).replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.default_branch",
        placeholders=placeholders,
    )
    master_runs, main_runs = response.results[0] if response.results else (0, 0)
    return "main" if (main_runs or 0) > (master_runs or 0) else "master"


def query_repo_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> RepoOverview:
    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    cur = "(run_started_at >= {date_from}" + (" AND run_started_at <= {date_to})" if date_to is not None else ")")
    prev = "(run_started_at >= {prev_from} AND run_started_at < {date_from})"

    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    runs_sql = (
        _RUNS_SELECT.replace("__CUR__", cur)
        .replace("__PREV__", prev)
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
    )
    runs_response = curated.run(
        runs_sql, query_type="engineering_analytics.repo_overview_runs", placeholders=placeholders
    )
    row = runs_response.results[0] if runs_response.results else (0, 0, None, None, 0, 0, 0, 0)
    run_count, run_count_prev, success_rate, success_rate_prev, reruns, reruns_prev, master_runs, main_runs = row
    default_branch = "main" if (main_runs or 0) > (master_runs or 0) else "master"

    pr_cur = "(merged_at >= {date_from}" + (" AND merged_at <= {date_to})" if date_to is not None else ")")
    pr_prev = "(merged_at >= {prev_from} AND merged_at < {date_from})"
    pr_sql = (
        _PR_SELECT.replace("__CUR_MERGED__", pr_cur)
        .replace("__PREV_MERGED__", pr_prev)
        .replace("__PR_SOURCE__", curated.pr_source())
    )
    pr_response = curated.run(pr_sql, query_type="engineering_analytics.repo_overview_prs", placeholders=placeholders)
    median_cur, median_prev = pr_response.results[0] if pr_response.results else (None, None)

    granularity = _pick_granularity(date_from, date_to)
    bucket_sql = (
        _BUCKET_SELECT.replace("__BUCKET_FN__", _BUCKET_FN[granularity])
        .replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
    )
    bucket_response = curated.run(
        bucket_sql,
        query_type="engineering_analytics.repo_overview_buckets",
        placeholders={**placeholders, "default_branch": ast.Constant(value=default_branch)},
    )
    by_bucket = {
        _normalize(bucket_start, granularity): RepoOverviewBucket(
            bucket_start=_normalize(bucket_start, granularity), completed=completed, successes=successes
        )
        for bucket_start, completed, successes in bucket_response.results or []
    }
    buckets = [
        by_bucket.get(bucket, RepoOverviewBucket(bucket_start=bucket, completed=0, successes=0))
        for bucket in _window_buckets(date_from, date_to, granularity)
    ]

    jobs_available = curated.jobs_source() is not None
    cost_cur = query_workflow_window_costs(curated=curated, date_from=date_from, date_to=date_to, branch=None)
    cost_prev = query_workflow_window_costs(curated=curated, date_from=prev_from, date_to=date_from, branch=None)
    # Per-workflow figures can be None (billable time on an unknown tier) — sum what's known.
    billable_seconds = sum(c.billable_seconds or 0.0 for c in cost_cur.values()) if cost_cur else None
    billable_seconds_prev = sum(c.billable_seconds or 0.0 for c in cost_prev.values()) if cost_prev else None
    cost_usd = sum(c.estimated_cost_usd or 0.0 for c in cost_cur.values()) if cost_cur else None
    cost_usd_prev = sum(c.estimated_cost_usd or 0.0 for c in cost_prev.values()) if cost_prev else None

    return RepoOverview(
        run_count=run_count,
        run_count_prev=run_count_prev,
        success_rate=_opt_float(success_rate),
        success_rate_prev=_opt_float(success_rate_prev),
        rerun_cycles=reruns,
        rerun_cycles_prev=reruns_prev,
        median_open_to_merge_seconds=_opt_float(median_cur),
        median_open_to_merge_seconds_prev=_opt_float(median_prev),
        billable_minutes=billable_seconds / 60 if billable_seconds is not None else None,
        billable_minutes_prev=billable_seconds_prev / 60 if billable_seconds_prev is not None else None,
        estimated_cost_usd=_opt_float(cost_usd),
        estimated_cost_usd_prev=_opt_float(cost_usd_prev),
        jobs_available=jobs_available,
        default_branch=default_branch,
        granularity=granularity,
        default_branch_buckets=buckets,
    )


def _opt_float(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
