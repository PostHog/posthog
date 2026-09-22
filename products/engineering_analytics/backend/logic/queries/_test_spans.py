"""The one definition of the per-test CI span scan and what it proves (domain rules defined once, APOSD).

Backend and Frontend CI emit one OTel span per signal-bearing test into the Traces store
(span name = runner-specific test identity, ``test.*`` attributes, ``ci.*`` resource attributes; see
``.github/scripts/report_test_timings.py``). Every query over that signal (the test-health
queue and the per-team rollups) embeds ``run_evidence()``, so the service fence, the signal
outcomes, the repository scoping, the ownership fallback, and above all the **grain** cannot
drift apart. Sharing a predicate string was not enough: each caller still counted its own way,
and they disagreed.

The grain is the CI run, not the span and not the run attempt:

- One run fans a test out across matrix legs (person-on-events, FOSS/EE, and friends), so span-grain
  counting multiplies a single failure by the number of legs that ran it. At run grain a failure in
  any leg counts once, and outweighs a pass in another.
- Every attempt of a run tests the same commit, so attempts are repeated trials: a run that both
  failed and passed a test has proven it nondeterministic, whichever attempt failed first. That is
  what ``recovered_in_run`` means. Recovery must happen in the same stable matrix job as the failure;
  a pass under a different configuration proves nothing. ``rerun_passed`` is the same proof from
  pytest's in-process retry, whose count survives in JUnit even when the final outcome is a pass.

Failures with no recovery prove nothing about determinism. This surface answers how much a failing
test costs us, so unproven failures are ranked by blast radius and never called flaky.
"""

from collections.abc import Sequence
from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM
from products.engineering_analytics.backend.logic.merge_queue import source_pr_string_expr
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import job_created_floor_constant

# On a merge-queue gate run the emitter stamps ``ci.pr_number`` from the webhook payload, which names
# the throwaway PR the queue opened rather than the PR being landed. Every blast-radius read here
# counts distinct PRs, so left alone one test failing across N merge attempts looks like N separate
# PRs hitting it — the branch is what names the real one (see ``logic.merge_queue``).
_SPAN_PR_NUMBER = source_pr_string_expr(
    "resource_attributes['ci.branch']", queue_actor_column="resource_attributes['ci.actor']"
)

# Only test spans carry test.outcome (job-root and setup spans don't), and only these
# outcomes are flaky signal. Plain 'skipped' spans never reach any aggregation; 'passed'
# spans are read only from re-run attempts (the scan's recovery arm), where they are the
# same-commit recovery proof.
SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Scope to the CI test-timing emitter (report_test_timings.py sets this as service.name);
# without it any team span carrying a test.outcome attribute would pollute.
PYTEST_CI_SERVICE_NAME = "ci-backend"
JEST_CI_SERVICE_NAME = "ci-frontend"
CI_SERVICE_NAMES = [PYTEST_CI_SERVICE_NAME, JEST_CI_SERVICE_NAME]


_RUN_EVIDENCE = """
    SELECT
        runner,
        nodeid,
        run_id,
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
            WHERE NOT has({setup_break_run_attempts}, (run_id, toString(attempt)))
                AND NOT has({setup_break_job_attempts}, (run_id, toString(attempt), job_key))
            GROUP BY runner, nodeid, run_id, job_key, attempt
        )
        GROUP BY runner, nodeid, run_id, job_key
        HAVING job_failed OR job_recovered OR job_quarantined
    )
    GROUP BY runner, nodeid, run_id
    -- The scan admits re-run passes so they can pair with a failure above; unpaired they are not
    -- evidence, and a pass-only row would surface as an all-zero test everywhere downstream.
    HAVING failed_in_run OR recovered_in_run OR quarantined_in_run
"""

# A CI setup break describes CI, not any one test, so run_evidence() drops every trial it produced: its
# failures are not failures of a test, and its passes are not recovery proof. It has two shapes:
# - a run attempt whose errored tests span many jobs, or tests of many owning teams;
# - a job attempt where many tests failed, such as a whole shard that fails and then passes on a re-run.
SETUP_BREAK_MIN_JOBS = 3
SETUP_BREAK_MIN_TEAMS = 3
SETUP_BREAK_MIN_JOB_FAILURES = 100

# The synthetic bucket _SCAN_TEMPLATE folds every keyless span into (pre-job_key history). It can
# merge failures from several real jobs, so it must never trigger the per-job-attempt exclusion below.
_LEGACY_JOB_KEY = "legacy"

# CI stamps every attribute the rules below read, and the warehouse is the side of the pair the
# emitter cannot write, so both must agree before any evidence is dropped.
_SETUP_BREAK_CANDIDATES = """
    SELECT run_id, attempt
    FROM (__SPAN_SCAN__)
    WHERE outcome = 'error'
    GROUP BY run_id, attempt
    HAVING uniq(job_key) >= {setup_break_min_jobs}
        OR uniqIf(owner_team, owner_team != {unowned_team}) >= {setup_break_min_teams}
"""

_SETUP_BREAK_JOB_CANDIDATES = """
    SELECT run_id, attempt, job_key
    FROM (__SPAN_SCAN__)
    WHERE outcome IN ('failed', 'error')
        AND job_key != {legacy_job_key}
    GROUP BY run_id, attempt, job_key
    HAVING uniq(nodeid) >= {setup_break_min_job_failures}
"""

# One failed job is enough for a job attempt: the jobs a run fans out over fail one at a time, and a
# shard that broke is one of them. A run attempt claims many jobs broke, so GitHub has to show as many.
_FAILED_JOB_COUNTS = """
    SELECT toString(run_id) AS run_id, run_attempt, uniqIf(name, conclusion = 'failure') AS failed_jobs
    FROM __JOBS_SOURCE__
    WHERE run_id IN {candidate_run_ids}
    GROUP BY run_id, run_attempt
"""


def run_evidence(*, bounded: bool) -> str:
    """One row per (test, CI run): what that run proves about that test.

    Every consumer groups this, never the raw spans, so all of them count at the same grain and
    agree on what the signal means. See the module docstring for why the run is the grain.

    ``bounded`` adds the upper time bound; some callers scan to now. The caller binds
    {setup_break_run_attempts} through ``scan_placeholders``, from ``query_setup_break_attempts``.
    """
    return _RUN_EVIDENCE.replace("__SPAN_SCAN__", _scan(bounded=bounded))


def _scan(*, bounded: bool) -> str:
    """The span scan with every ``__``-token substituted — the only way to obtain this SQL.

    An unsubstituted token is not a parse error you would notice, it is a silently wrong query, so
    every render goes through here rather than each caller remembering the list. The ``{...}`` names
    that remain are real HogQL placeholders, bound by ``scan_placeholders``.
    """
    return _SCAN_TEMPLATE.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "").replace(
        "__QUEUE_PR__", _SPAN_PR_NUMBER
    )


# Scans [scan_from, date_to?]; `is_current` splits rows at {date_from} so a caller scanning
# an extra prior window (scan_from < date_from) gets the current/prior split for free. A
# caller without a prior window passes scan_from = date_from and ignores the column.
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

    run_attempts: tuple[tuple[str, int], ...]
    job_attempts: tuple[tuple[str, int, str], ...]


def _attempt_array(attempts: Sequence[tuple[str | int, ...]]) -> ast.Array:
    # Every part is a string: a Python int would reach ClickHouse as a narrower type than the
    # column it is compared with, and the tuple would never match.
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

    Two sources have to agree. The spans name the attempts that look broken, and GitHub's synced job
    rows say which of those really failed. An attempt GitHub does not report as failed keeps its trials,
    so no test loses its evidence on the strength of the span attributes alone, and a team whose jobs
    table is unsynced drops nothing.
    """
    jobs_source = curated.jobs_source(created_floor=True)
    if not curated.repository or jobs_source is None:
        return SetupBreaks(run_attempts=(), job_attempts=())

    span_placeholders = scan_placeholders(
        repository=curated.repository, date_from=date_from, scan_from=scan_from, date_to=date_to
    )
    span_scan = _scan(bounded=date_to is not None)
    run_candidates = [
        (str(run_id), int(attempt))
        for run_id, attempt in _rows(
            curated,
            _SETUP_BREAK_CANDIDATES.replace("__SPAN_SCAN__", span_scan),
            query_type="engineering_analytics.setup_break_run_candidates",
            placeholders=span_placeholders,
            workload=Workload.LOGS,
        )
    ]
    job_candidates = [
        (str(run_id), int(attempt), str(job_key))
        for run_id, attempt, job_key in _rows(
            curated,
            _SETUP_BREAK_JOB_CANDIDATES.replace("__SPAN_SCAN__", span_scan),
            query_type="engineering_analytics.setup_break_job_candidates",
            placeholders=span_placeholders,
            workload=Workload.LOGS,
        )
    ]
    # An unstamped span falls back to its trace ID, which names no GitHub run.
    candidate_run_ids = sorted(
        {int(run_id) for run_id, _attempt in run_candidates if run_id.isdigit()}
        | {int(run_id) for run_id, _attempt, _job in job_candidates if run_id.isdigit()}
    )
    if not candidate_run_ids:
        return SetupBreaks(run_attempts=(), job_attempts=())

    failed_jobs_by_attempt = {
        (str(run_id), int(attempt)): int(failed_jobs)
        for run_id, attempt, failed_jobs in _rows(
            curated,
            _FAILED_JOB_COUNTS.replace("__JOBS_SOURCE__", jobs_source),
            query_type="engineering_analytics.setup_break_failed_jobs",
            placeholders={
                "candidate_run_ids": ast.Constant(value=candidate_run_ids),
                "job_created_floor": job_created_floor_constant(scan_from if scan_from is not None else date_from),
            },
        )
    }
    return SetupBreaks(
        run_attempts=tuple(
            sorted(
                attempt for attempt in run_candidates if failed_jobs_by_attempt.get(attempt, 0) >= SETUP_BREAK_MIN_JOBS
            )
        ),
        job_attempts=tuple(
            sorted(
                candidate
                for candidate in job_candidates
                if failed_jobs_by_attempt.get((candidate[0], candidate[1]), 0) >= 1
            )
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
          AND notEmpty(coalesce(attributes['test.runner_name'], ''))
    """


def selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span the CI reporter emitted before it stamped
    ``test.selector``. The nodeid folds the file/class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'); re-split on the convention that class segments are
    CamelCase and everything before them is the module file. Newer spans skip this: they carry the
    exact selector, built from JUnit's ``file`` where the boundary isn't guessed. Removable once every
    in-retention span carries ``test.selector`` (i.e. the emitter has been live longer than Traces
    retention).
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
