"""HogQL aggregation of per-test CI spans into the active test-health queue.

Backend CI emits one OTel span per test into the Traces store (span name = reconstructed pytest
nodeid, ``test.outcome`` span attribute, ``ci.*`` resource attributes, see
``.github/scripts/report_test_timings.py``).

The grain is the CI run, not the span and not the run attempt:

- A re-run re-uploads only the shards it re-executed, but the reporter emits every artifact it
  downloads, so an attempt re-reports shards it never ran. Counting attempts would multiply one
  failure by the number of re-runs.
- Every attempt of a run tests the same commit, so attempts are repeated trials: fail on one,
  pass on another, and the test is provably nondeterministic. Backend CI runs pytest without
  ``--reruns`` on purpose, so that is the only flake proof available; ``rerun_passed`` is the
  same proof from lanes that do enable in-job retries.

Failures without such a recovery are a suspected regression, qualified by blast radius instead.
Passes are read only to prove a recovery, and the emitter drops sub-threshold passes, so every
figure is an absolute count.

Reads the ``posthog.trace_spans`` table on the LOGS ClickHouse cluster, not the warehouse.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    FlakyTestClassification,
    FlakyTestItem,
    FlakyTestList,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Only test spans carry test.outcome, so this also filters out job-root and setup spans.
_SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Without this, any team span carrying a test.outcome attribute would pollute the aggregation.
_CI_SERVICE_NAME = "ci-backend"

_SELECT = """
    SELECT
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(recovered_in_run) AS same_commit_recovery_run_count,
        countIf(failed_in_run) AS failed_run_count,
        uniqIf(pr_number, failed_in_run AND pr_number != '') AS failed_pr_count,
        countIf(failed_in_run AND branch IN ('master', 'main')) AS master_failed_run_count,
        countIf(quarantined_in_run) AS quarantined_failed_run_count,
        max(run_signal_at) AS last_signal_at,
        multiIf(
            quarantined_failed_run_count > 0, 'quarantined',
            same_commit_recovery_run_count > 0, 'confirmed_flake',
            'suspected_regression'
        ) AS classification
    FROM (
        -- One row per (test, run).
        SELECT
            nodeid,
            anyIf(selector, selector != '') AS selector,
            anyIf(pr_number, pr_number != '') AS pr_number,
            anyIf(branch, branch != '') AS branch,
            max(trial_failed) AS failed_in_run,
            max(trial_quarantined) AS quarantined_in_run,
            max(trial_rerun_passed)
                OR (max(trial_failed) AND maxIf(attempt, trial_passed) > minIf(attempt, trial_failed))
                AS recovered_in_run,
            maxIf(trial_at, trial_failed OR trial_rerun_passed OR trial_quarantined) AS run_signal_at
        FROM (
            -- One row per (test, run attempt). An attempt reports every shard, so a test can appear
            -- in several matrix legs at once; a failure in any leg outweighs a pass in another.
            SELECT
                nodeid,
                run_id,
                attempt,
                anyIf(selector, selector != '') AS selector,
                anyIf(pr_number, pr_number != '') AS pr_number,
                anyIf(branch, branch != '') AS branch,
                max(outcome IN ('failed', 'error')) AS trial_failed,
                max(outcome = 'rerun_passed') AS trial_rerun_passed,
                max(outcome = 'xfailed') AS trial_quarantined,
                max(outcome = 'passed') AND NOT trial_failed AS trial_passed,
                max(span_timestamp) AS trial_at
            FROM (
                SELECT
                    name AS nodeid,
                    attributes['test.selector'] AS selector,
                    attributes['test.outcome'] AS outcome,
                    resource_attributes['ci.run_id'] AS run_id,
                    ifNull(accurateCastOrNull(resource_attributes['ci.run_attempt'], 'Int64'), 1) AS attempt,
                    resource_attributes['ci.pr_number'] AS pr_number,
                    resource_attributes['ci.branch'] AS branch,
                    timestamp AS span_timestamp
                FROM posthog.trace_spans
                WHERE service_name = {service_name}
                    AND lower(resource_attributes['ci.repository']) = lower({repository})
                    AND timestamp >= {date_from} __DATE_TO__
                    AND (
                        attributes['test.outcome'] IN {signal_outcomes}
                        -- A first attempt's pass can never prove a recovery, and the passing corpus
                        -- dwarfs the signal one, so it is never scanned.
                        OR (
                            attributes['test.outcome'] = 'passed'
                            AND resource_attributes['ci.run_attempt'] NOT IN ('', '1')
                        )
                    )
            )
            GROUP BY nodeid, run_id, attempt
        )
        GROUP BY nodeid, run_id
    )
    GROUP BY nodeid
    HAVING same_commit_recovery_run_count > 0
        OR quarantined_failed_run_count > 0
        OR master_failed_run_count > 0
        OR failed_pr_count >= {min_failed_prs}
    ORDER BY
        master_failed_run_count DESC,
        failed_pr_count DESC,
        failed_run_count DESC,
        last_signal_at DESC,
        nodeid ASC
    LIMIT {limit_plus_one}
"""


def _selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span the CI reporter emitted before it stamped
    ``test.selector``. The nodeid folds the file/class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'); re-split on the convention that class segments are
    CamelCase and everything before them is the module file. Newer spans skip this, they carry the
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


def query_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_failed_prs: int,
    limit: int,
) -> FlakyTestList:
    repository = curated.repository
    # Fail closed: the spans are scoped to the source's repository. Without a repository identity we
    # cannot tell one connected repo's spans from another, so return nothing rather than leak every
    # repository's flaky signals into the selected source's queue.
    if not repository:
        return FlakyTestList(items=[], truncated=False, limit=limit)

    date_to_clause = "AND timestamp <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=_CI_SERVICE_NAME),
        "signal_outcomes": ast.Constant(value=_SIGNAL_OUTCOMES),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "min_failed_prs": ast.Constant(value=min_failed_prs),
        # +1 so a full page tells us more tests qualified than returned.
        "limit_plus_one": ast.Constant(value=limit + 1),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    response = curated.run(
        _SELECT.replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.flaky_tests",
        placeholders=placeholders,
        # trace_spans lives on the LOGS ClickHouse cluster, not the warehouse default.
        workload=Workload.LOGS,
    )
    rows = response.results or []
    return FlakyTestList(
        items=[
            FlakyTestItem(
                nodeid=nodeid,
                # Prefer the emitter's exact selector; reconstruct from the nodeid for older spans.
                selector=selector or _selector_from_nodeid(nodeid),
                classification=FlakyTestClassification(classification),
                same_commit_recovery_run_count=same_commit_recovery_run_count,
                failed_run_count=failed_run_count,
                failed_pr_count=failed_pr_count,
                master_failed_run_count=master_failed_run_count,
                quarantined_failed_run_count=quarantined_failed_run_count,
                last_signal_at=last_signal_at,
            )
            for (
                nodeid,
                selector,
                same_commit_recovery_run_count,
                failed_run_count,
                failed_pr_count,
                master_failed_run_count,
                quarantined_failed_run_count,
                last_signal_at,
                classification,
            ) in rows[:limit]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )
