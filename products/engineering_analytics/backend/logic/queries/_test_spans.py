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
  a pass under a different configuration proves nothing. Backend CI runs pytest without ``--reruns``
  deliberately (failures stay visible instead of being retried away), so a "re-run failed jobs"
  recovery is where that proof comes from; ``rerun_passed`` is the same proof from the handful of
  tests hand-marked ``@pytest.mark.flaky(reruns=N)``.

Failures with no recovery prove nothing about determinism. This surface answers how much a failing
test costs us, so unproven failures are ranked by blast radius and never called flaky.
"""

from datetime import datetime

from posthog.hogql import ast

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

# Spans emitted before the owner stamp existed (or from paths with no owner) group here.
UNOWNED_TEAM = "unowned"


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


def run_evidence(*, bounded: bool) -> str:
    """One row per (test, CI run): what that run proves about that test.

    Every consumer groups this, never the raw spans, so all of them count at the same grain and
    agree on what the signal means. See the module docstring for why the run is the grain.

    ``bounded`` adds the upper time bound; some callers scan to now.
    """
    scan = _SCAN.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "")
    return _RUN_EVIDENCE.replace("__SPAN_SCAN__", scan)


# Scans [scan_from, date_to?]; `is_current` splits rows at {date_from} so a caller scanning
# an extra prior window (scan_from < date_from) gets the current/prior split for free. A
# caller without a prior window passes scan_from = date_from and ignores the column.
_SCAN = """
    SELECT
        if(attributes['test.runner'] = 'jest' OR service_name = 'ci-frontend', 'jest', 'pytest') AS runner,
        name AS nodeid,
        attributes['test.selector'] AS selector,
        attributes['test.outcome'] AS outcome,
        coalesce(nullIf(attributes['test.owner_team'], ''), {unowned_team}) AS owner_team,
        resource_attributes['ci.pr_number'] AS pr_number,
        resource_attributes['ci.branch'] AS branch,
        -- The emitter always stamps ci.run_id; the trace_id fallback (one trace per job) keeps an
        -- unstamped span from merging every execution of its test into one phantom run.
        coalesce(nullIf(resource_attributes['ci.run_id'], ''), trace_id) AS run_id,
        ifNull(accurateCastOrNull(resource_attributes['ci.run_attempt'], 'Int64'), 1) AS attempt,
        coalesce(nullIf(attributes['test.job_key'], ''), 'legacy') AS job_key,
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
) -> dict[str, ast.Expr]:
    placeholders: dict[str, ast.Expr] = {
        "service_names": ast.Constant(value=CI_SERVICE_NAMES),
        "signal_outcomes": ast.Constant(value=SIGNAL_OUTCOMES),
        "unowned_team": ast.Constant(value=UNOWNED_TEAM),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "scan_from": ast.Constant(value=scan_from if scan_from is not None else date_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    return placeholders


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
