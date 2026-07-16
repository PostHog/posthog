"""HogQL aggregation of per-test CI run evidence into the active test-health queue.

Groups ``_test_spans.run_evidence()`` (the one definition of the grain and of what a run proves)
by nodeid. A test is a confirmed flake only where that evidence shows a same-commit recovery;
failures without one prove nothing about determinism, so they qualify on blast radius instead and
are reported as a suspected regression.

Every figure is an absolute count: the emitter drops sub-threshold passes, so there is no
denominator to divide by.

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
    run_evidence,
    scan_placeholders,
    selector_from_nodeid,
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
    FROM (__RUN_EVIDENCE__)
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
        _SELECT.replace("__RUN_EVIDENCE__", run_evidence(bounded=date_to is not None)),
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
