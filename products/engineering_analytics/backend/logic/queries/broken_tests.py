"""Classifies recent CI failure fingerprints against the latest default-branch job status.

The failure lines live on the LOGS cluster and the job status on the warehouse cluster, so the
reads are merged in Python. When the jobs source is unsynced no fingerprint can classify as
``breaking_master`` or ``potentially_resolved``.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    BROKEN_TEST_SPARKLINE_HOURS,
    BrokenTestRow,
    BrokenTestsResult,
    BrokenTestState,
    CIEngine,
)
from products.engineering_analytics.backend.logic.merge_queue import looks_like_merge_queue_branch_expr
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    job_created_floor_constant,
)
from products.engineering_analytics.backend.logic.views import ci_failures

_DEFAULT_BRANCHES = ["master", "main"]

_RED_MASTER_SET = frozenset({"failure", "timed_out"})

_NOVEL_BURST_MAX_AGE_HOURS = 24
_NOVEL_BURST_MIN_BRANCHES = 3
_FLAKY_MIN_BRANCHES = 2
_FLAKY_MIN_SPAN_HOURS = 24

# The lowest rank sorts first.
_SEVERITY: dict[BrokenTestState, int] = {
    BrokenTestState.BREAKING_MASTER: 0,
    BrokenTestState.BLOCKING_MERGE_QUEUE: 1,
    BrokenTestState.NOVEL_BURST: 2,
    BrokenTestState.POTENTIALLY_RESOLVED: 3,
    BrokenTestState.FLAKY: 4,
    BrokenTestState.PR_ONLY: 5,
}

# The ages are integer dateDiffs against now(), so the Python classifier does no timezone math.
# The ORDER BY approximates severity, so the cap cannot evict a trunk-breaking fingerprint before
# the classifier runs.
_FINGERPRINTS_SELECT = """
    SELECT
        fingerprint,
        any(test_id) AS test_id,
        any(error_signature) AS error_signature,
        argMax(job_name, timestamp) AS job_name,
        min(timestamp) AS first_seen,
        max(timestamp) AS last_seen,
        dateDiff('hour', min(timestamp), now()) AS age_hours,
        dateDiff('hour', min(timestamp), max(timestamp)) AS span_hours,
        count() AS occurrences,
        uniqExactIf(branch, branch != '') AS branches,
        countIf(branch IN {default_branches}) AS master_hits,
        countIf(__MERGE_QUEUE_BRANCH__) AS merge_queue_hits,
        countIf(branch != '' AND branch NOT IN {default_branches} AND NOT __MERGE_QUEUE_BRANCH__) AS pr_branch_hits,
        -- Aliased away from `repo`: HogQL binds a WHERE identifier to a matching SELECT alias, so
        -- `any(repo) AS repo` would make the `lower(repo)` filter below resolve to this aggregate and
        -- 500 with "aggregate function found in WHERE". Keep the alias distinct from the filtered column.
        any(repo) AS repo_name,
        argMax(run_id, timestamp) AS latest_run_id,
        argMax(branch, timestamp) AS latest_branch,
        argMax(workflow_name, timestamp) AS workflow_name,
        dateDiff('second', maxIf(timestamp, branch IN {default_branches}), now()) AS last_master_hit_age,
        argMax(tuple(ci_engine), timestamp).1 AS latest_ci_engine
    FROM __FAILURES_SOURCE__
    WHERE timestamp >= {date_from} AND lower(repo) = lower({repository})
    GROUP BY fingerprint
    HAVING __FILTERS__
    ORDER BY master_hits DESC, merge_queue_hits DESC, branches DESC, last_seen DESC
    LIMIT {limit_plus_one}
"""

# hours_ago is 0 for the current hour. The scan is bounded to the fingerprints the first read kept.
_HOURLY_SELECT = f"""
    SELECT
        fingerprint,
        dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(now())) AS hours_ago,
        count() AS c
    FROM __FAILURES_SOURCE__
    WHERE timestamp >= {{hourly_from}} AND lower(repo) = lower({{repository}}) AND fingerprint IN {{fingerprints}}
    GROUP BY fingerprint, hours_ago
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# Keyed by engine and workflow as well as job name, because unrelated workflows reuse job names and
# one workflow's green job would mask another's red one. Recency keys on completed_at, because a
# job that started before a failure but finished green after it is a real recovery.
_MASTER_JOBS_SELECT = f"""
    SELECT
        workflow_name,
        name AS job_name,
        argMaxIf(conclusion, completed_at, status = 'completed') AS latest_conclusion,
        dateDiff('second', maxIf(completed_at, status = 'completed'), now()) AS latest_completed_age,
        ci_engine
    FROM __JOBS_SOURCE__
    WHERE head_branch IN {{default_branches}}
        AND created_at >= {{date_from}}
    GROUP BY ci_engine, workflow_name, name
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


def _classify(
    *,
    master_hits: int,
    merge_queue_hits: int,
    pr_branch_hits: int,
    age_hours: int,
    span_hours: int,
    branches: int,
    latest_conclusion: str | None,
    last_master_hit_age: int,
    latest_completed_age: int | None,
) -> BrokenTestState:
    """``latest_conclusion`` and ``latest_completed_age`` describe the matched default-branch job, and
    are None when it has no status. ``last_master_hit_age`` is meaningful only when ``master_hits > 0``.
    Ages are seconds before now, except ``age_hours`` and ``span_hours``."""
    master_red = latest_conclusion in _RED_MASTER_SET
    # A green job that finished before the newest trunk failure is a stale status, not a recovery.
    master_green_and_fresh = (
        latest_conclusion == "success"
        and latest_completed_age is not None
        and latest_completed_age < last_master_hit_age
    )
    if master_hits > 0 and master_red:
        return BrokenTestState.BREAKING_MASTER
    # The failure must happen only on gate branches. The queue runs the full suite on every merge
    # attempt, so an ordinary flake also collects gate hits.
    if merge_queue_hits > 0 and master_hits == 0 and pr_branch_hits == 0:
        return BrokenTestState.BLOCKING_MERGE_QUEUE
    if age_hours < _NOVEL_BURST_MAX_AGE_HOURS and branches >= _NOVEL_BURST_MIN_BRANCHES and master_hits == 0:
        return BrokenTestState.NOVEL_BURST
    if master_hits > 0 and master_green_and_fresh:
        return BrokenTestState.POTENTIALLY_RESOLVED
    if branches >= _FLAKY_MIN_BRANCHES and span_hours > _FLAKY_MIN_SPAN_HOURS:
        return BrokenTestState.FLAKY
    return BrokenTestState.PR_ONLY


def _sparklines_by_fingerprint(hourly_rows: list) -> dict[str, list[int]]:
    """Hourly counts per fingerprint, oldest slot first. A fingerprint with no failures in the
    window has no entry."""
    series_by_fp: dict[str, list[int]] = {}
    for fingerprint, hours_ago, count in hourly_rows:
        if hours_ago < 0 or hours_ago >= BROKEN_TEST_SPARKLINE_HOURS:
            continue
        series = series_by_fp.setdefault(fingerprint, [0] * BROKEN_TEST_SPARKLINE_HOURS)
        series[BROKEN_TEST_SPARKLINE_HOURS - 1 - hours_ago] += count
    return series_by_fp


def query_broken_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    hourly_from: datetime,
    window_days: int,
    limit: int,
    test: str | None = None,
    branch: str | None = None,
) -> BrokenTestsResult:
    repository = curated.repository
    # The failure-lines view is team-global, so without a repository to scope it the read would mix
    # in another repo's failures.
    if not repository:
        return BrokenTestsResult(
            rows=[], breaking_master_jobs=[], window_days=window_days, truncated=False, limit=limit
        )

    failures_source = f"({ci_failures.build_query()})"
    logs_placeholders: dict[str, ast.Expr] = {
        "default_branches": ast.Constant(value=_DEFAULT_BRANCHES),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "limit_plus_one": ast.Constant(value=limit + 1),
    }
    # The filters sit in HAVING because `test_id` in WHERE would bind to the `any(test_id)` alias.
    filters = ["1"]
    if test:
        filters.append("positionCaseInsensitive(test_id, {test}) > 0")
        logs_placeholders["test"] = ast.Constant(value=test)
    # The branch filter keeps a fingerprint that failed there, but its counts still cover every branch.
    if branch:
        filters.append("countIf(branch = {branch}) > 0")
        logs_placeholders["branch"] = ast.Constant(value=branch)
    # The gate-branch match reads the branch name alone, because the failure lines carry no actor.
    fingerprints_sql = (
        _FINGERPRINTS_SELECT.replace("__MERGE_QUEUE_BRANCH__", looks_like_merge_queue_branch_expr("branch"))
        .replace("__FAILURES_SOURCE__", failures_source)
        .replace("__FILTERS__", " AND ".join(filters))
    )
    fingerprint_rows = (
        curated.run(
            fingerprints_sql,
            query_type="engineering_analytics.broken_tests_fingerprints",
            placeholders=logs_placeholders,
            workload=Workload.LOGS,
        ).results
        or []
    )
    selected_fingerprints = [row[0] for row in fingerprint_rows]
    hourly_rows = (
        (
            curated.run(
                _HOURLY_SELECT.replace("__FAILURES_SOURCE__", failures_source),
                query_type="engineering_analytics.broken_tests_hourly",
                placeholders={
                    "repository": ast.Constant(value=repository),
                    "hourly_from": ast.Constant(value=hourly_from),
                    "fingerprints": ast.Constant(value=selected_fingerprints),
                },
                workload=Workload.LOGS,
            ).results
            or []
        )
        if selected_fingerprints
        else []
    )

    master_by_key: dict[tuple[str | None, str, str], tuple[str | None, int | None]] = {}
    breaking_master_jobs: set[str] = set()
    jobs_source = curated.jobs_source(created_floor=True, since=date_from)
    if jobs_source is not None:
        master_rows = (
            curated.run(
                _MASTER_JOBS_SELECT.replace("__JOBS_SOURCE__", jobs_source),
                query_type="engineering_analytics.broken_tests_master_jobs",
                placeholders={
                    "default_branches": ast.Constant(value=_DEFAULT_BRANCHES),
                    "job_created_floor": job_created_floor_constant(date_from),
                    "date_from": ast.Constant(value=date_from),
                },
            ).results
            or []
        )
        for workflow_name, job_name, latest_conclusion, latest_completed_age, ci_engine in master_rows:
            master_by_key[(ci_engine, workflow_name, job_name)] = (latest_conclusion, latest_completed_age)
            if latest_conclusion in _RED_MASTER_SET:
                breaking_master_jobs.add(job_name)

    # A log line with no engine uses the status only when its workflow and job names identify one engine.
    by_job: dict[tuple[str, str], list[tuple[str | None, int | None]]] = {}
    for (_engine, workflow, job), status in master_by_key.items():
        by_job.setdefault((workflow, job), []).append(status)
    for (workflow, job), statuses in by_job.items():
        if len(statuses) == 1:
            master_by_key[(None, workflow, job)] = statuses[0]
    sparklines = _sparklines_by_fingerprint(hourly_rows)

    rows: list[BrokenTestRow] = []
    for (
        fingerprint,
        test_id,
        error_signature,
        job_name,
        first_seen,
        last_seen,
        age_hours,
        span_hours,
        occurrences,
        branches,
        master_hits,
        merge_queue_hits,
        pr_branch_hits,
        repo,
        latest_run_id,
        latest_branch,
        workflow_name,
        last_master_hit_age,
        latest_ci_engine,
    ) in fingerprint_rows:
        latest_conclusion, latest_completed_age = master_by_key.get(
            (latest_ci_engine, workflow_name, job_name), (None, None)
        )
        state = _classify(
            master_hits=master_hits,
            merge_queue_hits=merge_queue_hits,
            pr_branch_hits=pr_branch_hits,
            age_hours=age_hours,
            span_hours=span_hours,
            branches=branches,
            latest_conclusion=latest_conclusion,
            last_master_hit_age=last_master_hit_age,
            latest_completed_age=latest_completed_age,
        )
        rows.append(
            BrokenTestRow(
                fingerprint=fingerprint,
                test_id=test_id or "",
                error_signature=error_signature or "",
                job_name=job_name or "",
                repo=repo or "",
                state=state,
                first_seen=first_seen,
                last_seen=last_seen,
                occurrences=occurrences,
                branches=branches,
                master_hits=master_hits,
                latest_run_id=latest_run_id or 0,
                latest_ci_engine=CIEngine(latest_ci_engine) if latest_ci_engine else None,
                latest_branch=latest_branch or "",
                trend_24h=sparklines.get(fingerprint, [0] * BROKEN_TEST_SPARKLINE_HOURS),
            )
        )

    # Two stable sorts order the rows by severity, then by newest failure within each state.
    rows.sort(key=lambda r: r.last_seen, reverse=True)
    rows.sort(key=lambda r: _SEVERITY[r.state])
    return BrokenTestsResult(
        rows=rows[:limit],
        breaking_master_jobs=sorted(breaking_master_jobs),
        window_days=window_days,
        truncated=len(rows) > limit,
        limit=limit,
    )
