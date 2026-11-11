"""The per-test CI span scan, emitted by ``.github/scripts/report_test_timings.py``.

Test evidence is counted per CI run, never per span or per run attempt. A run fans a test out
across matrix legs, and every attempt of a run tests the same commit. A test that both failed and
passed in the same matrix job of one run is proven nondeterministic (``recovered_in_run``).
"""

from collections.abc import Sequence
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.ownership.paths import UNOWNED_TEAM

from products.engineering_analytics.backend.logic.merge_queue import source_pr_string_expr
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import job_created_floor_constant

# On a merge-queue gate run ``ci.pr_number`` names the throwaway PR the queue opened, so one test
# failing across several merge attempts would count as several PRs. The branch names the PR being landed.
_SPAN_PR_NUMBER = source_pr_string_expr(
    "resource_attributes['ci.branch']", queue_actor_column="resource_attributes['ci.actor']"
)

# The scan also reads 'passed' spans, but only from re-run attempts, as recovery proof.
SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# The service names report_test_timings.py emits. Without this filter any span of the team that
# carries a test.outcome attribute would count.
PYTEST_CI_SERVICE_NAME = "ci-backend"
JEST_CI_SERVICE_NAME = "ci-frontend"
CI_SERVICE_NAMES = [PYTEST_CI_SERVICE_NAME, JEST_CI_SERVICE_NAME]


_RUN_EVIDENCE = """
    SELECT
        runner,
        nodeid,
        run_id,
        ci_engine,
        workflow_run_key,
        head_sha,
        argMax(owner_team, job_at) AS owner_team,
        anyIf(selector, selector != '') AS selector,
        anyIf(pr_number, pr_number != '') AS pr_number,
        anyIf(branch, branch != '') AS branch,
        max(is_current) AS is_current,
        max(job_failed) AS failed_in_run,
        max(job_quarantined) AS quarantined_in_run,
        max(job_recovered) AS recovered_in_run,
        -- Recovery passes are not signal, so recency comes from the signal trials alone.
        max(job_signal_at) AS run_signal_at
    FROM (
        -- One row per stable matrix job and run. Recovery can only pair trials from this job; a
        -- FOSS pass cannot recover an EE failure, nor can one backend matrix leg recover another.
        SELECT
            runner,
            nodeid,
            run_id,
            ci_engine,
            workflow_run_key,
            head_sha,
            argMax(owner_team, trial_at) AS owner_team,
            anyIf(selector, selector != '') AS selector,
            anyIf(pr_number, pr_number != '') AS pr_number,
            anyIf(branch, branch != '') AS branch,
            max(is_current) AS is_current,
            max(trial_failed) AS job_failed,
            max(trial_quarantined) AS job_quarantined,
            -- Proof of nondeterminism either way it lands: an in-job retry recovered the test, or
            -- one attempt of this job failed it and another attempt (same commit) passed it.
            max(trial_rerun_passed) OR (max(trial_failed) AND max(trial_passed)) AS job_recovered,
            maxIf(trial_at, trial_failed OR trial_rerun_passed OR trial_quarantined) AS job_signal_at,
            max(trial_at) AS job_at
        FROM (
            -- One row per (test, stable job, run attempt). A failure in one duplicate span
            -- outweighs a pass in that same trial.
            SELECT
                runner,
                nodeid,
                run_id,
            ci_engine,
            workflow_run_key,
            head_sha,
                job_key,
                argMax(owner_team, span_timestamp) AS owner_team,
                anyIf(selector, selector != '') AS selector,
                anyIf(pr_number, pr_number != '') AS pr_number,
                anyIf(branch, branch != '') AS branch,
                max(is_current) AS is_current,
                max(outcome IN ('failed', 'error')) AS trial_failed,
                max(outcome = 'rerun_passed') AS trial_rerun_passed,
                max(outcome = 'xfailed') AS trial_quarantined,
                max(outcome = 'passed') AND NOT trial_failed AS trial_passed,
                max(span_timestamp) AS trial_at
            FROM (__SPAN_SCAN__)
            WHERE NOT has({setup_break_run_attempts}, (ci_engine, workflow_run_key, toString(attempt)))
                AND NOT has({setup_break_job_attempts}, (ci_engine, workflow_run_key, toString(attempt), job_key))
            GROUP BY runner, nodeid, ci_engine, workflow_run_key, head_sha, run_id, job_key, attempt
        )
        GROUP BY runner, nodeid, ci_engine, workflow_run_key, head_sha, run_id, job_key
        HAVING job_failed OR job_recovered OR job_quarantined
    )
    GROUP BY runner, nodeid, ci_engine, workflow_run_key, head_sha, run_id
    -- The scan admits re-run passes so they can pair with a failure above; unpaired they are not
    -- evidence, and a pass-only row would surface as an all-zero test everywhere downstream.
    HAVING failed_in_run OR recovered_in_run OR quarantined_in_run
"""

# A CI setup break describes CI, not any one test, so run_evidence() drops every trial it produced.
# It is a run attempt whose errored tests span many jobs or owning teams, or a job attempt where
# many tests failed.
SETUP_BREAK_MIN_JOBS = 3
SETUP_BREAK_MIN_TEAMS = 3
SETUP_BREAK_MIN_JOB_FAILURES = 100

# _SCAN_TEMPLATE folds every span with no job key into this bucket. It can merge failures from
# several jobs, so it must never trigger the per-job-attempt exclusion.
_LEGACY_JOB_KEY = "legacy"

_SETUP_BREAK_CANDIDATES = """
    SELECT ci_engine, workflow_run_key, attempt
    FROM (__SPAN_SCAN__)
    WHERE outcome = 'error'
    GROUP BY ci_engine, workflow_run_key, attempt
    HAVING uniq(job_key) >= {setup_break_min_jobs}
        OR uniqIf(owner_team, owner_team != {unowned_team}) >= {setup_break_min_teams}
"""

_SETUP_BREAK_JOB_CANDIDATES = """
    SELECT ci_engine, workflow_run_key, attempt, job_key
    FROM (__SPAN_SCAN__)
    WHERE outcome IN ('failed', 'error')
        AND job_key != {legacy_job_key}
    GROUP BY ci_engine, workflow_run_key, attempt, job_key
    HAVING uniq(nodeid) >= {setup_break_min_job_failures}
"""

_FAILED_JOB_COUNTS = """
    SELECT ci_engine,
        if(native_workflow_run_id IN {candidate_workflow_keys}, native_workflow_run_id, toString(run_id)) AS workflow_run_key,
        run_attempt, uniqIf(name, conclusion = 'failure') AS failed_jobs
    FROM __JOBS_SOURCE__
    WHERE run_id IN {candidate_run_ids} OR native_workflow_run_id IN {candidate_workflow_keys}
    GROUP BY ci_engine, workflow_run_key, run_attempt
"""


def run_evidence(*, bounded: bool) -> str:
    """One row per (test, CI run): what that run proves about that test.

    ``bounded`` adds the {date_to} upper bound. The caller binds the placeholders with
    ``scan_placeholders``, passing the ``SetupBreaks`` from ``query_setup_breaks``.
    """
    return _RUN_EVIDENCE.replace("__SPAN_SCAN__", _scan(bounded=bounded))


def _scan(*, bounded: bool) -> str:
    """``_SCAN_TEMPLATE`` with every ``__`` token substituted. ``scan_placeholders`` binds the rest."""
    return _SCAN_TEMPLATE.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "").replace(
        "__QUEUE_PR__", _SPAN_PR_NUMBER
    )


# `is_current` splits rows at {date_from}, for a caller that also scans a prior window
# (scan_from < date_from).
_SCAN_TEMPLATE = """
    SELECT
        if(attributes['test.runner'] = 'jest' OR service_name = 'ci-frontend', 'jest', 'pytest') AS runner,
        name AS nodeid,
        attributes['test.selector'] AS selector,
        attributes['test.outcome'] AS outcome,
        -- An '@handle' stamp is a person from an owners.yaml first slot, not a team; older
        -- spans carry them, so fold them into the unowned bucket instead of minting a row.
        if(
            startsWith(coalesce(attributes['test.owner_team'], ''), '@'),
            {unowned_team},
            coalesce(nullIf(attributes['test.owner_team'], ''), {unowned_team})
        ) AS owner_team,
        if(__QUEUE_PR__ != '', __QUEUE_PR__, resource_attributes['ci.pr_number']) AS pr_number,
        resource_attributes['ci.branch'] AS branch,
        -- The emitter always stamps ci.run_id; the trace_id fallback (one trace per job) keeps an
        -- unstamped span from merging every execution of its test into one phantom run.
        coalesce(nullIf(resource_attributes['ci.run_id'], ''), trace_id) AS run_id,
        coalesce(resource_attributes['ci.engine'], '') AS ci_engine,
        coalesce(resource_attributes['ci.sha'], '') AS head_sha,
        -- A Depot parent can contain several workflows; without their native IDs do not pair retries.
        coalesce(nullIf(resource_attributes['ci.native_workflow_run_id'], ''), if(ci_engine = 'depot_ci', trace_id, run_id)) AS workflow_run_key,
        ifNull(accurateCastOrNull(resource_attributes['ci.run_attempt'], 'Int64'), 1) AS attempt,
        coalesce(nullIf(attributes['test.job_key'], ''), {legacy_job_key}) AS job_key,
        timestamp AS span_timestamp,
        timestamp >= {date_from} AS is_current
    FROM posthog.trace_spans
    WHERE service_name IN {service_names}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
        -- Only re-run attempts' passes are read. Reading first-attempt passes too would mean
        -- scanning the whole passing corpus, which dwarfs the signal one, to gain only the runs
        -- whose disagreement began with a pass (passed on attempt 1, failed on the re-run).
        AND (
            attributes['test.outcome'] IN {signal_outcomes}
            OR (
                attributes['test.outcome'] = 'passed'
                AND resource_attributes['ci.run_attempt'] NOT IN ('', '1')
            )
        )
"""


def scan_placeholders(
    *,
    repository: str,
    date_from: datetime,
    scan_from: datetime | None = None,
    date_to: datetime | None = None,
    setup_breaks: "SetupBreaks | None" = None,
) -> dict[str, ast.Expr]:
    setup_breaks = setup_breaks if setup_breaks is not None else SetupBreaks(run_attempts=(), job_attempts=())
    placeholders: dict[str, ast.Expr] = {
        "service_names": ast.Constant(value=CI_SERVICE_NAMES),
        "signal_outcomes": ast.Constant(value=SIGNAL_OUTCOMES),
        "unowned_team": ast.Constant(value=UNOWNED_TEAM),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "scan_from": ast.Constant(value=scan_from if scan_from is not None else date_from),
        "setup_break_min_jobs": ast.Constant(value=SETUP_BREAK_MIN_JOBS),
        "setup_break_min_teams": ast.Constant(value=SETUP_BREAK_MIN_TEAMS),
        "setup_break_min_job_failures": ast.Constant(value=SETUP_BREAK_MIN_JOB_FAILURES),
        "legacy_job_key": ast.Constant(value=_LEGACY_JOB_KEY),
        "setup_break_run_attempts": _attempt_array(setup_breaks.run_attempts),
        "setup_break_job_attempts": _attempt_array(setup_breaks.job_attempts),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    return placeholders


@frozen
class SetupBreaks:
    """The CI setup breaks a window holds, keyed the way ``run_evidence()`` excludes them."""

    run_attempts: tuple[tuple[str, str, int], ...]
    job_attempts: tuple[tuple[str, str, int, str], ...]


def _attempt_array(attempts: Sequence[tuple[str | int, ...]]) -> ast.Array:
    # A Python int would reach ClickHouse as a narrower type than the column it is compared with,
    # and the tuple would never match.
    return ast.Array(
        exprs=[ast.Tuple(exprs=[ast.Constant(value=str(part)) for part in attempt]) for attempt in attempts]
    )


def query_setup_breaks(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    scan_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SetupBreaks:
    """The setup breaks of this window, for ``scan_placeholders``.

    The spans name the attempts that look broken, and the synced job rows must confirm them: a run
    attempt needs ``SETUP_BREAK_MIN_JOBS`` failed jobs, a job attempt needs one. CI stamps the span
    attributes, so spans alone drop no evidence, and an unsynced jobs table drops nothing.
    """
    floor_from = scan_from if scan_from is not None else date_from
    jobs_source = curated.jobs_source(created_floor=True, since=floor_from)
    if not curated.repository or jobs_source is None:
        return SetupBreaks(run_attempts=(), job_attempts=())

    span_placeholders = scan_placeholders(
        repository=curated.repository, date_from=date_from, scan_from=scan_from, date_to=date_to
    )
    span_scan = _scan(bounded=date_to is not None)
    run_candidates = [
        (str(ci_engine), str(workflow_key), int(attempt))
        for ci_engine, workflow_key, attempt in _rows(
            curated,
            _SETUP_BREAK_CANDIDATES.replace("__SPAN_SCAN__", span_scan),
            query_type="engineering_analytics.setup_break_run_candidates",
            placeholders=span_placeholders,
            workload=Workload.LOGS,
        )
    ]
    job_candidates = [
        (str(ci_engine), str(workflow_key), int(attempt), str(job_key))
        for ci_engine, workflow_key, attempt, job_key in _rows(
            curated,
            _SETUP_BREAK_JOB_CANDIDATES.replace("__SPAN_SCAN__", span_scan),
            query_type="engineering_analytics.setup_break_job_candidates",
            placeholders=span_placeholders,
            workload=Workload.LOGS,
        )
    ]
    # An unstamped span falls back to its trace ID, which names no GitHub run.
    candidate_run_ids = sorted(
        {int(workflow_key) for _engine, workflow_key, _attempt in run_candidates if workflow_key.isdigit()}
        | {int(workflow_key) for _engine, workflow_key, _attempt, _job in job_candidates if workflow_key.isdigit()}
    )
    candidate_workflow_keys = sorted({candidate[1] for candidate in (*run_candidates, *job_candidates)})
    if not candidate_workflow_keys:
        return SetupBreaks(run_attempts=(), job_attempts=())

    failed_jobs_by_attempt = {
        (str(ci_engine), str(workflow_key), int(attempt)): int(failed_jobs)
        for ci_engine, workflow_key, attempt, failed_jobs in _rows(
            curated,
            _FAILED_JOB_COUNTS.replace("__JOBS_SOURCE__", jobs_source),
            query_type="engineering_analytics.setup_break_failed_jobs",
            placeholders={
                "candidate_run_ids": ast.Constant(value=candidate_run_ids),
                "candidate_workflow_keys": ast.Constant(value=candidate_workflow_keys),
                "job_created_floor": job_created_floor_constant(floor_from),
            },
        )
    }
    # A span with no engine can use the job rows only where its workflow key names one engine.
    engines_by_workflow: dict[str, set[str]] = {}
    for engine, workflow_key, _attempt in failed_jobs_by_attempt:
        engines_by_workflow.setdefault(workflow_key, set()).add(engine)
    for (_engine, workflow_key, attempt), failures in list(failed_jobs_by_attempt.items()):
        if len(engines_by_workflow[workflow_key]) == 1:
            failed_jobs_by_attempt[("", workflow_key, attempt)] = failures
    return SetupBreaks(
        run_attempts=tuple(
            sorted(
                attempt for attempt in run_candidates if failed_jobs_by_attempt.get(attempt, 0) >= SETUP_BREAK_MIN_JOBS
            )
        ),
        job_attempts=tuple(
            sorted(candidate for candidate in job_candidates if failed_jobs_by_attempt.get(candidate[:3], 0) >= 1)
        ),
    )


def _rows(
    curated: CuratedGitHubSource,
    sql: str,
    *,
    query_type: str,
    placeholders: dict[str, ast.Expr],
    workload: Workload = Workload.DEFAULT,
) -> list:
    return curated.run(sql, query_type=query_type, placeholders=placeholders, workload=workload).results or []


def rerun_recovered_job_attempts(*, scan_from: str) -> str:
    """``(run_id, run_attempt, runner_name)``, as strings, of every pytest job attempt whose in-process
    retry recovered a test. That job concludes as a success, but its log still holds the failure.

    ``scan_from`` is a HogQL expression for the earliest span to read. The caller binds ``{repository}``.
    """
    return f"""
        SELECT resource_attributes['ci.run_id'], resource_attributes['ci.run_attempt'],
               attributes['test.runner_name']
        FROM posthog.trace_spans
        WHERE service_name = '{PYTEST_CI_SERVICE_NAME}'
          AND lower(resource_attributes['ci.repository']) = lower({{repository}})
          AND timestamp >= ({scan_from})
          AND attributes['test.outcome'] = 'rerun_passed'
          AND coalesce(resource_attributes['ci.engine'], 'github_actions') = 'github_actions'
          AND notEmpty(coalesce(attributes['test.runner_name'], ''))
    """


def selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span with no ``test.selector``.

    The nodeid folds the file and class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'). This assumes class segments are CamelCase and
    everything before them is the module file. Remove it once every span in Traces retention
    carries ``test.selector``.
    """
    class_path, sep, test_part = nodeid.partition("::")
    if not sep or "/" not in class_path:
        return nodeid
    segments = class_path.split("/")
    module_end = len(segments)
    while module_end > 1 and segments[module_end - 1][:1].isupper():
        module_end -= 1
    module = "/".join(segments[:module_end]) + ".py"
    return "::".join([module, *segments[module_end:], test_part])
