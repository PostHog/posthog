"""Broken-tests classifier: rank live CI failures by how they're behaving right now.

The flaky-test leaderboard answers "which tests are unreliable over a week". This answers a
sharper, more urgent question: of the failures happening *right now*, which are breaking trunk,
which are a new failure catching on, which are just one PR's problem. It reads the fingerprinted
failure lines (``engineering_analytics_ci_failures`` — the Logs-backed view) over a short window,
groups them into distinct failures, and classifies each against the latest default-branch job
status. The classifier lives here (not in the UI) so the same verdict backs both the panel and,
later, the Signals emitter — detection defined once over the read layer (SPEC §3).

Three reads, merged in Python because they span two ClickHouse clusters:

- fingerprints + the 24h sparkline histogram — both over the failure-lines view on the LOGS
  cluster (scoped by ``repo`` since that view is team-global, not source-scoped);
- latest default-branch job status — over the curated ``workflow_jobs`` source on the warehouse
  cluster, keyed by job name.

Age, span, and sparkline offsets are computed in SQL as integer ``dateDiff``s against ``now()`` so
the Python classifier never does timezone-sensitive datetime math on the returned values.

``breaking_master`` / ``potentially_resolved`` need the failure's job to match a default-branch job
by name (the log record's ``job_name`` vs the warehouse job ``name``). When the job-level source
isn't synced there is no job status at all, so those fingerprints fall through to ``flaky`` /
``pr_only`` — the panel degrades rather than misreports.
"""

from datetime import datetime, timedelta

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    BROKEN_TEST_SPARKLINE_HOURS,
    BrokenTestRow,
    BrokenTestsResult,
    BrokenTestState,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.views import ci_failures

# Branch names treated as trunk — the failure "hit master" and job-status filters key on these.
_DEFAULT_BRANCHES = ["master", "main"]

# Job conclusions that mean trunk is red right now.
_RED_MASTER_SET = frozenset({"failure", "timed_out"})

# Classifier thresholds (heuristics over the failure fingerprints).
_NOVEL_BURST_MAX_AGE_HOURS = 24  # "new today" — first seen within the last day
_NOVEL_BURST_MIN_BRANCHES = 3  # ...and already spreading across at least this many branches
_FLAKY_MIN_BRANCHES = 2  # sporadic on at least two branches
_FLAKY_MIN_SPAN_HOURS = 24  # ...and recurring over more than a day

# Sort rank: lowest surfaces first (breaking master on top, PR-only last).
_SEVERITY: dict[BrokenTestState, int] = {
    BrokenTestState.BREAKING_MASTER: 0,
    BrokenTestState.NOVEL_BURST: 1,
    BrokenTestState.POTENTIALLY_RESOLVED: 2,
    BrokenTestState.FLAKY: 3,
    BrokenTestState.PR_ONLY: 4,
}

# Fingerprint aggregation over the failure-lines view. ``age_hours`` / ``span_hours`` are computed
# here (integer dateDiffs against now()) so the Python classifier stays timezone-agnostic. The
# HAVING keeps only failures that spread beyond one branch or reached trunk — a single PR's own
# fresh failure is noise here. Capped at limit+1 (by recency) so a full page reveals truncation;
# the final severity ranking happens after classification.
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
        uniqExact(branch) AS branches,
        countIf(branch IN {default_branches}) AS master_hits,
        any(repo) AS repo,
        argMax(run_id, timestamp) AS latest_run_id,
        argMax(branch, timestamp) AS latest_branch
    FROM __FAILURES_SOURCE__
    WHERE timestamp >= {date_from} AND lower(repo) = lower({repository})
    GROUP BY fingerprint
    HAVING branches >= 2 OR master_hits > 0
    ORDER BY last_seen DESC
    LIMIT {limit_plus_one}
"""

# Per-fingerprint hourly failure counts over the last day, bucketed by how many whole hours ago the
# hour was (0 = current hour). Its own tight 24h scan (not the analysis window) because the
# sparkline answers "is this escalating right now"; folded into a fixed array per fingerprint below.
_HOURLY_SELECT = """
    SELECT
        fingerprint,
        dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(now())) AS hours_ago,
        count() AS c
    FROM __FAILURES_SOURCE__
    WHERE timestamp >= {hourly_from} AND lower(repo) = lower({repository})
    GROUP BY fingerprint, hours_ago
"""

# Latest default-branch status per job, from the curated workflow-jobs source. ``created_at_raw`` is
# the raw ISO string the scan can prune on (a parsed-column predicate forces a full scan); it floors
# a day below the precise ``created_at`` window. ``latest_conclusion`` is the newest completed run's
# conclusion — red means trunk is broken for that job right now, green means it recovered.
_MASTER_JOBS_SELECT = """
    SELECT
        name AS job_name,
        argMaxIf(conclusion, created_at, status = 'completed') AS latest_conclusion
    FROM __JOBS_SOURCE__
    WHERE head_branch IN {default_branches}
        AND created_at_raw >= {created_floor}
        AND created_at >= {date_from}
    GROUP BY name
"""


def _classify(
    *, master_hits: int, age_hours: int, span_hours: int, branches: int, latest_conclusion: str | None
) -> BrokenTestState:
    """The broken-test verdict for one fingerprint. ``latest_conclusion`` is the matched default-branch
    job's newest completed conclusion, or None when the job has no default-branch status (job source
    unsynced, or the failure's job never ran on trunk)."""
    master_red = latest_conclusion in _RED_MASTER_SET
    master_green = latest_conclusion == "success"
    # Breaking trunk right now: hit the default branch and that job's latest run is still red.
    if master_hits > 0 and master_red:
        return BrokenTestState.BREAKING_MASTER
    # New today and already spreading across branches, but not on trunk yet.
    if age_hours < _NOVEL_BURST_MAX_AGE_HOURS and branches >= _NOVEL_BURST_MIN_BRANCHES and master_hits == 0:
        return BrokenTestState.NOVEL_BURST
    # Hit the default branch but that job is green again — probably already fixed.
    if master_hits > 0 and master_green:
        return BrokenTestState.POTENTIALLY_RESOLVED
    # Sporadic across branches and recurring over more than a day.
    if branches >= _FLAKY_MIN_BRANCHES and span_hours > _FLAKY_MIN_SPAN_HOURS:
        return BrokenTestState.FLAKY
    return BrokenTestState.PR_ONLY


def _sparklines_by_fingerprint(hourly_rows: list) -> dict[str, list[int]]:
    """Fold the (fingerprint, hours_ago, count) rows into a fixed hourly array per fingerprint,
    oldest slot first. Buckets outside the window are ignored; a fingerprint with no recent failures
    simply gets no entry (the caller renders all-zeros)."""
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
) -> BrokenTestsResult:
    repository = curated.repository
    # The failure-lines view is team-global; without a source repository we cannot scope it to the
    # selected source, so return nothing rather than mix another repo's failures in.
    if not repository:
        return BrokenTestsResult(
            rows=[], breaking_master_jobs=[], window_days=window_days, truncated=False, limit=limit
        )

    failures_source = f"({ci_failures.build_query()})"
    logs_placeholders: dict[str, ast.Expr] = {
        "default_branches": ast.Constant(value=_DEFAULT_BRANCHES),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        # +1 so a full page reveals that more fingerprints qualified than returned.
        "limit_plus_one": ast.Constant(value=limit + 1),
    }
    fingerprint_rows = (
        curated.run(
            _FINGERPRINTS_SELECT.replace("__FAILURES_SOURCE__", failures_source),
            query_type="engineering_analytics.broken_tests_fingerprints",
            placeholders=logs_placeholders,
            workload=Workload.LOGS,
        ).results
        or []
    )
    hourly_rows = (
        curated.run(
            _HOURLY_SELECT.replace("__FAILURES_SOURCE__", failures_source),
            query_type="engineering_analytics.broken_tests_hourly",
            placeholders={
                "repository": ast.Constant(value=repository),
                "hourly_from": ast.Constant(value=hourly_from),
            },
            workload=Workload.LOGS,
        ).results
        or []
    )

    # Latest default-branch status per job — empty when the job-level source isn't synced, in which
    # case breaking_master / potentially_resolved can't be distinguished and those rows fall through.
    master_by_job: dict[str, str | None] = {}
    breaking_master_jobs: list[str] = []
    jobs_source = curated.jobs_source()
    if jobs_source is not None:
        master_rows = (
            curated.run(
                _MASTER_JOBS_SELECT.replace("__JOBS_SOURCE__", jobs_source),
                query_type="engineering_analytics.broken_tests_master_jobs",
                placeholders={
                    "default_branches": ast.Constant(value=_DEFAULT_BRANCHES),
                    "created_floor": ast.Constant(value=(date_from - timedelta(days=1)).strftime("%Y-%m-%d")),
                    "date_from": ast.Constant(value=date_from),
                },
            ).results
            or []
        )
        for job_name, latest_conclusion in master_rows:
            master_by_job[job_name] = latest_conclusion
            if latest_conclusion in _RED_MASTER_SET:
                breaking_master_jobs.append(job_name)

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
        repo,
        latest_run_id,
        latest_branch,
    ) in fingerprint_rows:
        state = _classify(
            master_hits=master_hits,
            age_hours=age_hours,
            span_hours=span_hours,
            branches=branches,
            latest_conclusion=master_by_job.get(job_name),
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
                latest_branch=latest_branch or "",
                trend_24h=sparklines.get(fingerprint, [0] * BROKEN_TEST_SPARKLINE_HOURS),
            )
        )

    # Severity first, then most-recent failure — the top of the list is what's on fire right now.
    # Two stable passes (Python's sort is stable): newest last_seen within each state, states in
    # rank order. All last_seen values come from one query, so they're uniformly comparable.
    rows.sort(key=lambda r: r.last_seen, reverse=True)
    rows.sort(key=lambda r: _SEVERITY[r.state])
    return BrokenTestsResult(
        rows=rows[:limit],
        breaking_master_jobs=sorted(breaking_master_jobs),
        window_days=window_days,
        truncated=len(rows) > limit,
        limit=limit,
    )
