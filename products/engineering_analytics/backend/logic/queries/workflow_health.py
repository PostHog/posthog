"""Curated query: per-workflow CI health over a window.

Run counts, success rate, and duration percentiles per ``workflow_name`` for runs
started within ``[date_from, date_to]`` (``date_to`` optional), optionally scoped to
a single ``head_branch`` and/or attributed pull-request runs. Rates are over completed
runs. Duration percentiles are over successful runs only — cancelled/skipped runs
(common on PR branches, where a new push supersedes in-flight CI) and failed runs
end early and would bias a "how long does CI take" percentile low — so they are
``None`` for a window with no successful runs. No-op gate runs are excluded from the
percentiles too, with an all-successful fallback for legitimately all-fast workflows
(see ``run_duration_percentile_expr``), so the Workflows table agrees with the
activity chart and the detail-page KPIs.

The per-bucket history adapts its granularity to the window length (hour / day / week)
so the trend sparkline keeps a readable number of points — per-day buckets are useless
for a 24h window and far too many for a year.
"""

from dataclasses import dataclass
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    RepoRef,
    TimeToGreenBucket,
    WorkflowHealthBucket,
    WorkflowHealthItem,
    WorkflowHealthRunScope,
)
from products.engineering_analytics.backend.logic.queries._buckets import (
    Granularity,
    bucket_expr,
    normalize_bucket,
    pick_granularity,
    window_buckets,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource, opt_float
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    LATEST_COMPLETED_RUN_FAILED,
    RUN_DURATION_PERCENTILE_CONDITION,
    branch_filter_clause,
    date_to_filter_clause,
    non_default_branch_predicate,
    run_duration_percentile_expr,
    run_scope_filter_clause,
    run_started_floor_constant,
    window_pair_predicates,
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
        countIf(status = 'completed' AND conclusion = 'success') AS successful_run_count,
        countIf(status = 'completed' AND conclusion IN ('success', 'failure', 'timed_out')) AS conclusive_run_count,
        countIf({RUN_DURATION_PERCENTILE_CONDITION}) AS percentile_run_count,
        countIf(status = 'completed' AND conclusion = 'success') / nullIf(countIf(status = 'completed'), 0) AS success_rate,
        {run_duration_percentile_expr(0.5)} AS p50_seconds,
        {run_duration_percentile_expr(0.95)} AS p95_seconds,
        max(if(conclusion IN ('failure', 'timed_out'), run_started_at, NULL)) AS last_failure_at,
        countIf(status = 'completed') AS completed_count,
        {LATEST_COMPLETED_RUN_FAILED} AS latest_failed,
        argMaxIf(conclusion, (run_started_at, id), status = 'completed') AS latest_conclusion,
        argMaxIf(id, (run_started_at, id), status = 'completed') AS latest_run_id,
        argMaxIf(run_attempt, (run_started_at, id), status = 'completed') AS latest_run_attempt,
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


# A push round is one (repo, head_sha): every workflow GitHub fired for that push. The measure is the
# wall from the round's first run start to the moment its last workflow first completed benign: the
# question a PR author asks ("how long until this push is green"), which no single run answers.
#
# Each workflow anchors on its FIRST benign completion, never its latest run: a flake re-run stretches
# the wall to its recovery, while a re-fire after the round already went green cannot stretch it
# retroactively. Benign is wider than success (a path-filtered workflow reports 'skipped' and holds
# nothing back) and narrower than "not a decisive failure": a cancelled run reached no verdict.
#
# A round that can't be measured honestly is a non-sample, never a shorter one:
#   - a workflow with no benign completion (still running, or it never passed)
#   - no workflow that actually succeeded, so the round only ever skipped
#   - partial attribution: fork-PR runs land unassociated, so a per-run ``pr_number`` filter would
#     read a fork push as green in seconds. A round with any unattributed sibling drops out whole.
#
# Known overstatement: a workflow whose first run on the SHA lands late (marking a draft ready fires
# workflows a draft never ran) stretches the wall, because the round really wasn't green until it
# passed, so the wall then also covers the hours the PR sat in draft. Distinguishing that from a
# slow queue would need a re-fire gap threshold, which is a number nobody can defend.
_TIME_TO_GREEN_CTES = f"""
    WITH workflows_on_push AS (
        SELECT
            repo_owner,
            repo_name,
            head_sha,
            workflow_name,
            min(pr_number > 0) AS attributed,
            min(run_started_at) AS first_start,
            min(if(
                status = 'completed' AND coalesce(conclusion, '') IN ('success', 'skipped', 'neutral'),
                updated_at, NULL
            )) AS first_green_end,
            countIf(status = 'completed' AND conclusion = 'success') > 0 AS has_success
        FROM __RUNS_SOURCE__ AS r
        WHERE run_started_at >= {{scan_from}} __DATE_TO__
          AND NOT r.is_merge_queue
          AND {non_default_branch_predicate()}
        GROUP BY repo_owner, repo_name, head_sha, workflow_name
    ),
    green_rounds AS (
        SELECT
            min(first_start) AS round_start,
            dateDiff('second', min(first_start), max(first_green_end)) AS wall_seconds
        FROM workflows_on_push
        GROUP BY repo_owner, repo_name, head_sha
        HAVING min(attributed) = 1
           AND countIf(first_green_end IS NULL) = 0
           AND countIf(has_success) > 0
    )
"""

_TIME_TO_GREEN_SELECT = (
    _TIME_TO_GREEN_CTES
    + f"""
    SELECT
        __BUCKET_FN__ AS bucket_start,
        quantile(0.5)(wall_seconds) AS p50_seconds
    FROM green_rounds
    GROUP BY bucket_start
    LIMIT {_BUCKET_LIMIT}
"""
)

_TIME_TO_GREEN_WINDOW_SELECT = (
    _TIME_TO_GREEN_CTES
    + """
    SELECT
        quantileIf(0.5)(wall_seconds, __CUR__) AS p50_cur,
        quantileIf(0.5)(wall_seconds, __PREV__) AS p50_prev
    FROM green_rounds
"""
)


def query_time_to_green_series(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    granularity: Granularity,
) -> list[TimeToGreenBucket]:
    """Median wall clock from a push round's first run start to all its workflows first green, per
    bucket, oldest first, keyed on the bucket the round started in. Only fully green, fully attributed
    rounds are samples (``_TIME_TO_GREEN_SELECT`` has the exclusions and the one known overstatement);
    an empty bucket carries ``p50_seconds`` None (a gap, not instant CI)."""
    placeholders: dict[str, ast.Expr] = {
        "scan_from": ast.Constant(value=date_from),
        "run_started_floor": run_started_floor_constant(date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    sql = (
        _TIME_TO_GREEN_SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__DATE_TO__", date_to_clause)
        .replace("__BUCKET_FN__", bucket_expr(granularity, "round_start"))
    )
    response = curated.run(sql, query_type="engineering_analytics.time_to_green_series", placeholders=placeholders)
    p50_by_bucket = {
        normalize_bucket(bucket_start, granularity): opt_float(p50_seconds)
        for bucket_start, p50_seconds in response.results or []
    }
    return [
        TimeToGreenBucket(bucket_start=bucket, p50_seconds=p50_by_bucket.get(bucket))
        for bucket in window_buckets(date_from, date_to, granularity)
    ]


@dataclass(frozen=True, kw_only=True)
class TimeToGreenWindow:
    """Median wall clock for a fully green push round over a window and its previous twin — the
    same population and exclusions as the time-to-green series."""

    median_seconds: float | None
    median_seconds_prev: float | None


def query_time_to_green_window(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    prev_from: datetime,
) -> TimeToGreenWindow:
    """Window-level time-to-green medians for [date_from, date_to] and [prev_from, date_from], one
    scan, keyed on the bucketless equivalent of the series' round_start."""
    windows = window_pair_predicates("round_start", date_to=date_to)
    placeholders: dict[str, ast.Expr] = {
        "scan_from": ast.Constant(value=prev_from),
        "date_from": ast.Constant(value=date_from),
        "prev_from": ast.Constant(value=prev_from),
        "run_started_floor": run_started_floor_constant(prev_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    sql = (
        _TIME_TO_GREEN_WINDOW_SELECT.replace("__RUNS_SOURCE__", curated.run_source(started_floor=True))
        .replace("__DATE_TO__", date_to_clause)
        .replace("__CUR__", windows.current)
        .replace("__PREV__", windows.previous)
    )
    response = curated.run(sql, query_type="engineering_analytics.time_to_green_window", placeholders=placeholders)
    p50_cur, p50_prev = response.results[0] if response.results else (None, None)
    return TimeToGreenWindow(median_seconds=opt_float(p50_cur), median_seconds_prev=opt_float(p50_prev))


def query_workflow_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str | None,
    run_scope: WorkflowHealthRunScope,
    workload: Workload = Workload.DEFAULT,
) -> list[WorkflowHealthItem]:
    granularity = pick_granularity(date_from, date_to)
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "run_started_floor": run_started_floor_constant(date_from),
    }
    date_to_clause = date_to_filter_clause(date_to, placeholders)
    branch_clause = branch_filter_clause(branch, placeholders)
    run_scope_clause = run_scope_filter_clause(run_scope)

    runs_source = curated.run_source(started_floor=True)

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
        workload=workload,
    )
    if not response.results:
        return []

    bucket_response = curated.run(
        fill(_BUCKET_SELECT),
        query_type="engineering_analytics.workflow_health_buckets",
        placeholders=placeholders,
        workload=workload,
    )

    end = date_to or datetime.now(tz=date_from.tzinfo)
    prev_from = date_from - (end - date_from)
    prev_response = curated.run(
        fill(_PREV_SELECT),
        query_type="engineering_analytics.workflow_health_prev",
        # The prev window scans [prev_from, date_from); its scan floor must come from prev_from, not
        # date_from, or the raw prefilter would cut every previous-window row before the parsed filter.
        placeholders={
            **placeholders,
            "prev_from": ast.Constant(value=prev_from),
            "run_started_floor": run_started_floor_constant(prev_from),
        },
        workload=workload,
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
        curated=curated, date_from=date_from, date_to=date_to, branch=branch, run_scope=run_scope, workload=workload
    )
    window = window_buckets(date_from, date_to, granularity)
    return [
        WorkflowHealthItem(
            repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
            workflow_name=workflow_name,
            run_count=run_count,
            successful_run_count=successful_run_count,
            conclusive_run_count=conclusive_run_count,
            percentile_run_count=percentile_run_count,
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
            latest_run_id=int(latest_run_id) if completed_count else None,
            latest_run_attempt=int(latest_run_attempt) if completed_count else None,
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
        for repo_owner, repo_name, workflow_name, run_count, successful_run_count, conclusive_run_count, percentile_run_count, success_rate, p50_seconds, p95_seconds, last_failure_at, completed_count, latest_failed, latest_conclusion, latest_run_id, latest_run_attempt, rerun_cycles in response.results
    ]
