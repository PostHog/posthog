"""The one definition of the per-test CI span scan and what it proves (domain rules defined once, APOSD).

Backend CI emits one OTel span per test into the Traces store (span name = reconstructed
pytest nodeid, ``test.*`` attributes, ``ci.*`` resource attributes; see
``.github/scripts/report_test_timings.py``). Every query over that signal (the test-health
queue and the per-team rollups) embeds ``run_evidence()``, so the service fence, the signal
outcomes, the repository scoping, the ownership fallback, and above all the **grain** cannot
drift apart. Sharing a predicate string was not enough: each caller still counted its own way,
and they disagreed.

The grain is the CI run, not the span and not the run attempt:

- A re-run re-uploads only the shards it re-executed, but the reporter emits every artifact it
  downloads, so an attempt re-reports shards it never ran. Counting spans or attempts multiplies
  one failure by the number of re-runs.
- Every attempt of a run tests the same commit, so attempts are repeated trials: a run that both
  failed and passed a test has proven it nondeterministic, whichever attempt failed first. That is
  what ``recovered_in_run`` means, and it is the only proof of flakiness this telemetry carries.
  Backend CI runs pytest without ``--reruns`` on purpose, so a GitHub re-run is where it comes
  from; ``rerun_passed`` is the same proof from lanes that do enable in-job retries.

Failures with no such recovery prove nothing about determinism, so callers classify them on blast
radius instead and must never call them flaky.
"""

from datetime import datetime

from posthog.hogql import ast

# Only test spans carry test.outcome (job-root and setup spans don't), and only these
# outcomes are flaky signal; plain 'passed'/'skipped' spans never reach any aggregation.
SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Scope to the CI test-timing emitter (report_test_timings.py sets this as service.name);
# without it any team span carrying a test.outcome attribute would pollute.
CI_SERVICE_NAME = "ci-backend"

# Spans emitted before the owner stamp existed (or from paths with no owner) group here.
UNOWNED_TEAM = "unowned"


_RUN_EVIDENCE = """
    SELECT
        nodeid,
        run_id,
        argMax(owner_team, trial_at) AS owner_team,
        anyIf(selector, selector != '') AS selector,
        anyIf(pr_number, pr_number != '') AS pr_number,
        anyIf(branch, branch != '') AS branch,
        max(is_current) AS is_current,
        max(trial_failed) AS failed_in_run,
        max(trial_quarantined) AS quarantined_in_run,
        max(trial_rerun_passed) OR (max(trial_failed) AND max(trial_passed)) AS recovered_in_run,
        max(trial_at) AS run_at,
        maxIf(trial_at, trial_failed OR trial_rerun_passed OR trial_quarantined) AS run_signal_at
    FROM (
        -- One row per (test, run attempt). An attempt reports every shard, so a test can appear in
        -- several matrix legs at once; a failure in any leg outweighs a pass in another.
        SELECT
            nodeid,
            run_id,
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
        GROUP BY nodeid, run_id, attempt
    )
    GROUP BY nodeid, run_id
"""


def run_evidence(*, bounded: bool) -> str:
    """One row per (test, CI run): what that run proves about that test.

    Every consumer groups this, never the raw spans, so all of them count at the same grain and
    agree on what "flaky" means. See the module docstring for why the run is the grain.
    """
    return _RUN_EVIDENCE.replace("__SPAN_SCAN__", span_scan(bounded=bounded, with_run_attempts=True))


# Scans [scan_from, date_to?]; `is_current` splits rows at {date_from} so a caller scanning
# an extra prior window (scan_from < date_from) gets the current/prior split for free. A
# caller without a prior window passes scan_from = date_from and ignores the column.
_SCAN = """
    SELECT
        name AS nodeid,
        attributes['test.selector'] AS selector,
        attributes['test.outcome'] AS outcome,
        coalesce(nullIf(attributes['test.owner_team'], ''), {unowned_team}) AS owner_team,
        resource_attributes['ci.pr_number'] AS pr_number,
        resource_attributes['ci.branch'] AS branch,__RUN_COLUMNS__
        timestamp AS span_timestamp,
        timestamp >= {date_from} AS is_current
    FROM posthog.trace_spans
    WHERE service_name = {service_name}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
        AND (attributes['test.outcome'] IN {signal_outcomes}__RECOVERY_ARM__)
"""

_RUN_COLUMNS = """
        resource_attributes['ci.run_id'] AS run_id,
        ifNull(accurateCastOrNull(resource_attributes['ci.run_attempt'], 'Int64'), 1) AS attempt,"""

# Only re-run attempts' passes are read. Reading first-attempt passes too would mean scanning the
# whole passing corpus, which dwarfs the signal one, to gain only the runs whose disagreement began
# with a pass (passed on attempt 1, failed on the re-run). That is real proof, and this misses it.
_RECOVERY_ARM = """
            OR (
                attributes['test.outcome'] = 'passed'
                AND resource_attributes['ci.run_attempt'] NOT IN ('', '1')
            )"""


def span_scan(*, bounded: bool, with_run_attempts: bool = False) -> str:
    """The scan SELECT, with or without the upper time bound (some callers scan to now).

    ``with_run_attempts`` adds ``run_id`` / ``attempt`` and widens the outcome fence to include
    re-run passes, which is what lets a caller group at run grain and see a same-commit recovery.
    """
    return (
        _SCAN.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "")
        .replace("__RUN_COLUMNS__", _RUN_COLUMNS if with_run_attempts else "")
        .replace("__RECOVERY_ARM__", _RECOVERY_ARM if with_run_attempts else "")
    )


def scan_placeholders(
    *,
    repository: str,
    date_from: datetime,
    scan_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, ast.Expr]:
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=CI_SERVICE_NAME),
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
