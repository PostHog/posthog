"""HogQL aggregation of per-test CI spans into the active test-health queue.

Embeds the shared per-test span scan (``_test_spans``, the one definition of the service fence,
signal outcomes, and repository scoping), grouped at run grain.

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
from products.engineering_analytics.backend.logic.queries._test_spans import (
    scan_placeholders,
    selector_from_nodeid,
    span_scan,
)

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
            FROM (__SPAN_SCAN__)
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

    placeholders = scan_placeholders(repository=repository, date_from=date_from, date_to=date_to)
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    # +1 so a full page tells us more tests qualified than returned.
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)

    response = curated.run(
        _SELECT.replace("__SPAN_SCAN__", span_scan(bounded=date_to is not None, with_run_attempts=True)),
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
                selector=selector or selector_from_nodeid(nodeid),
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
