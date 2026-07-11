"""Curated query: per-workflow CI health over a window.

Run counts, success rate, and duration percentiles per ``workflow_name`` for runs
started within ``[date_from, date_to]`` (``date_to`` optional), optionally scoped to
a single ``head_branch`` and/or attributed pull-request runs. Rates are over completed
runs. Duration percentiles are over successful runs only — cancelled/skipped runs
(common on PR branches, where a new push supersedes in-flight CI) and failed runs
end early and would bias a "how long does CI take" percentile low — so they are
``None`` for a window with no successful runs.

The per-bucket history adapts its granularity to the window length (hour / day / week)
so the trend sparkline keeps a readable number of points — per-day buckets are useless
for a 24h window and far too many for a year.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    RepoRef,
    TimeToGreenBucket,
    WorkflowHealthBucket,
    WorkflowHealthItem,
    WorkflowHealthRunScope,
)
from products.engineering_analytics.backend.logic.queries._buckets import (
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DURATION_PERCENTILE_CONDITION,
    branch_filter_clause,
    date_to_filter_clause,
    run_scope_filter_clause,
)
from products.engineering_analytics.backend.logic.queries.pr_cost import query_workflow_window_costs

_LIMIT = 100
# Generous bound: _LIMIT workflows x at most ~366 daily buckets.
_BUCKET_LIMIT = 40000

_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        count() AS run_count,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate,
        quantileIf(0.5)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p50_seconds,
        quantileIf(0.95)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p95_seconds,
        max(if(conclusion IN ('failure', 'timed_out'), run_started_at, NULL)) AS last_failure_at,
        countIf(status = 'completed') AS completed_count,
        argMaxIf(conclusion IN ('failure', 'timed_out'), run_started_at, status = 'completed') AS latest_failed,
        argMaxIf(conclusion, run_started_at, status = 'completed') AS latest_conclusion,
        countIf(run_attempt > 1) AS rerun_cycles
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY repo_owner, repo_name, workflow_name
    ORDER BY run_count DESC
    LIMIT {_LIMIT}
"""

# Success rate over the equal-length window before date_from — the delta baseline the UI renders as
# an honest Δpp instead of a server-baked percentage. Kept as its own slim scan so the main query's
# window (and its LIMIT semantics) stay untouched.
_PREV_SELECT = """
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {prev_from} AND run_started_at < {date_from} __BRANCH__ __RUN_SCOPE__
    GROUP BY repo_owner, repo_name, workflow_name
"""

_BUCKET_SELECT = f"""
    SELECT
        repo_owner,
        repo_name,
        workflow_name,
        __BUCKET_FN__ AS bucket_start,
        count() AS run_count,
        countIf(status = 'completed') AS completed,
        countIf(status = 'completed' AND conclusion = 'success') AS successes,
        countIf(status = 'completed' AND conclusion IN ('failure', 'timed_out')) AS failures
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__ __BRANCH__ __RUN_SCOPE__
    GROUP BY repo_owner, repo_name, workflow_name, bucket_start
    LIMIT {_BUCKET_LIMIT}
"""


_TIME_TO_GREEN_SELECT = f"""
    SELECT
        __BUCKET_FN__ AS bucket_start,
        quantileIf(0.5)(duration_seconds, {DURATION_PERCENTILE_CONDITION}) AS p50_seconds
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__ __RUN_SCOPE__
    GROUP BY bucket_start
    LIMIT {_BUCKET_LIMIT}
"""


def query_time_to_green_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
) -> tuple[str, list[TimeToGreenBucket]]:
    """Median time-to-green per bucket across the window, oldest first: the p50 wall-clock duration of
    successful, PR-attributed CI runs (default-branch runs excluded). Success-only + PR-scoped — the same
    population workflow-health's percentiles use — so it answers "how long until CI passes on a PR", not
    master build time. Empty buckets carry ``p50_seconds`` None (a gap, not instant CI)."""
    granularity = pick_granularity(date_from, date_to)
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    run_scope_clause = run_scope_filter_clause(WorkflowHealthRunScope.PULL_REQUEST)
    sql = (
        _TIME_TO_GREEN_SELECT.replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__DATE_TO__", date_to_clause)
        .replace("__RUN_SCOPE__", run_scope_clause)
        .replace("__BUCKET_FN__", bucket_expr(granularity))
    )
    response = curated.run(sql, query_type="engineering_analytics.time_to_green_series", placeholders=placeholders)
    p50_by_bucket = {
        normalize_bucket(bucket_start, granularity): opt_float(p50_seconds)
        for bucket_start, p50_seconds in response.results or []
    }
    buckets = [
        TimeToGreenBucket(bucket_start=bucket, p50_seconds=p50_by_bucket.get(bucket))
        for bucket in window_buckets(date_from, date_to, granularity)
    ]
    return granularity, buckets


def query_workflow_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
    run_scope: WorkflowHealthRunScope,
) -> list[WorkflowHealthItem]:
    granularity = pick_granularity(date_from, date_to)
    placeholders: dict[str, ast.Expr] = {"date_from": ast.Constant(value=date_from)}
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    branch_clause = branch_filter_clause(branch, placeholders)
    run_scope_clause = run_scope_filter_clause(run_scope)

    runs_source = curated.run_source()

    def fill(template: str) -> str:
        return (
            template.replace("__RUNS_SOURCE__", runs_source)
            .replace("__DATE_TO__", date_to_clause)
            .replace("__BRANCH__", branch_clause)
            .replace("__RUN_SCOPE__", run_scope_clause)
            .replace("__BUCKET_FN__", bucket_expr(granularity))
        )

    response = curated.run(
        fill(_SELECT),
        query_type="engineering_analytics.workflow_health",
        placeholders=placeholders,
    )
    if not response.results:
        return []

    bucket_response = curated.run(
        fill(_BUCKET_SELECT),
        query_type="engineering_analytics.workflow_health_buckets",
        placeholders=placeholders,
    )

    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)
    prev_response = curated.run(
        fill(_PREV_SELECT),
        query_type="engineering_analytics.workflow_health_prev",
        placeholders={**placeholders, "prev_from": ast.Constant(value=prev_from)},
    )
    prev_rate_by_workflow: dict[tuple[str, str, str], float | None] = {
        (repo_owner, repo_name, workflow_name): opt_float(success_rate)
        for repo_owner, repo_name, workflow_name, success_rate in prev_response.results or []
    }
    buckets_by_workflow: dict[tuple[str, str, str], dict[datetime, WorkflowHealthBucket]] = {}
    for repo_owner, repo_name, workflow_name, bucket_start, run_count, completed, successes, failures in (
        bucket_response.results or []
    ):
        key = normalize_bucket(bucket_start, granularity)
        buckets_by_workflow.setdefault((repo_owner, repo_name, workflow_name), {})[key] = WorkflowHealthBucket(
            bucket_start=key, run_count=run_count, completed=completed, successes=successes, failures=failures
        )

    cost_by_workflow = query_workflow_window_costs(
        curated=curated, date_from=date_from, date_to=date_to, branch=branch, run_scope=run_scope
    )
    window = window_buckets(date_from, date_to, granularity)
    return [
        WorkflowHealthItem(
            repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
            workflow_name=workflow_name,
            run_count=run_count,
            success_rate=opt_float(success_rate),
            p50_seconds=opt_float(p50_seconds),
            p95_seconds=opt_float(p95_seconds),
            last_failure_at=last_failure_at,
            # argMaxIf defaults to 0 when nothing completed; the completed_count guard tells
            # "latest run passed" apart from "no completed run yet".
            latest_run_failed=bool(latest_failed) if completed_count else None,
            # The raw conclusion of that latest completed run, so the UI can tell a real pass from a
            # cancelled/skipped run (both have latest_run_failed false). None when nothing completed.
            latest_run_conclusion=(latest_conclusion or None) if completed_count else None,
            granularity=granularity,
            buckets=[
                buckets_by_workflow.get((repo_owner, repo_name, workflow_name), {}).get(
                    bucket, WorkflowHealthBucket(bucket_start=bucket, run_count=0, completed=0, successes=0, failures=0)
                )
                for bucket in window
            ],
            billable_minutes=(
                cost_by_workflow[workflow_name].billable_seconds / 60 if workflow_name in cost_by_workflow else None
            ),
            estimated_cost_usd=(
                cost_by_workflow[workflow_name].estimated_cost_usd if workflow_name in cost_by_workflow else None
            ),
            rerun_cycles=rerun_cycles,
            success_rate_prev=prev_rate_by_workflow.get((repo_owner, repo_name, workflow_name)),
        )
        for repo_owner, repo_name, workflow_name, run_count, success_rate, p50_seconds, p95_seconds, last_failure_at, completed_count, latest_failed, latest_conclusion, rerun_cycles in response.results
    ]
