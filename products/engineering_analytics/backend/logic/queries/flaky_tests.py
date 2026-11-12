"""The test-health queue: ``_test_spans.run_evidence()`` grouped by nodeid and ranked by blast radius.

Every figure is an absolute count, because the emitter drops sub-threshold passes and leaves no
denominator.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    CITestRunner,
    FlakyTestClassification,
    FlakyTestItem,
    FlakyTestList,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    query_setup_breaks,
    run_evidence,
    scan_placeholders,
    selector_from_nodeid,
)

_SELECT = """
    SELECT
        runner,
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(recovered_in_run) AS same_commit_recovery_run_count,
        countIf(failed_in_run) AS failed_run_count,
        uniqIf(pr_number, failed_in_run AND pr_number != '') AS failed_pr_count,
        countIf(failed_in_run AND branch IN ('master', 'main')) AS master_failed_run_count,
        countIf(quarantined_in_run) AS quarantined_failed_run_count,
        max(run_signal_at) AS last_signal_at
    FROM (__RUN_EVIDENCE__)
    WHERE __TEST_FILTERS__
    GROUP BY runner, nodeid
    HAVING (
        same_commit_recovery_run_count > 0
        OR quarantined_failed_run_count > 0
        OR master_failed_run_count > 0
        OR failed_pr_count >= {min_failed_prs}
    ) AND __SCOPE_FILTERS__
    ORDER BY
        master_failed_run_count DESC,
        failed_pr_count DESC,
        failed_run_count DESC,
        last_signal_at DESC,
        nodeid ASC,
        runner ASC
    LIMIT {limit_plus_one}
"""


def query_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_failed_prs: int,
    limit: int,
    runner: CITestRunner | None,
    test: str | None = None,
    branch: str | None = None,
    pr_number: int | None = None,
) -> FlakyTestList:
    repository = curated.repository
    # Spans are scoped by repository. Without a repository identity the read would return every
    # connected repository's spans, so it returns nothing.
    if not repository:
        return FlakyTestList(items=[], truncated=False, limit=limit)

    placeholders = scan_placeholders(
        repository=repository,
        date_from=date_from,
        date_to=date_to,
        setup_breaks=query_setup_breaks(curated=curated, date_from=date_from, date_to=date_to),
    )
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    test_filters = ["1"]
    if runner is not None:
        test_filters.append("runner = {runner}")
        placeholders["runner"] = ast.Constant(value=runner.value)
    # A branch or PR scope keeps a test that has evidence there, but counts all of its evidence, so
    # the row still shows whether the test also fails elsewhere.
    scope_filters = ["1"]
    if test:
        # The nodeid drops '.py' and folds the file/class boundary into '/', so a pytest selector
        # or file path only matches the selector. In HAVING, `selector` is the row's selector.
        scope_filters.append(
            "(positionCaseInsensitive(nodeid, {test}) > 0 OR positionCaseInsensitive(selector, {test}) > 0)"
        )
        placeholders["test"] = ast.Constant(value=test)
    if branch:
        scope_filters.append("countIf(branch = {branch}) > 0")
        placeholders["branch"] = ast.Constant(value=branch)
    if pr_number is not None:
        scope_filters.append("countIf(pr_number = {pr_number}) > 0")
        placeholders["pr_number"] = ast.Constant(value=str(pr_number))
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)

    query = (
        _SELECT.replace("__RUN_EVIDENCE__", run_evidence(bounded=date_to is not None))
        .replace("__TEST_FILTERS__", " AND ".join(test_filters))
        .replace("__SCOPE_FILTERS__", " AND ".join(scope_filters))
    )

    response = curated.run(
        query,
        query_type="engineering_analytics.flaky_tests",
        placeholders=placeholders,
        # trace_spans lives on the LOGS ClickHouse cluster, not the warehouse default.
        workload=Workload.LOGS,
    )
    rows = response.results or []
    return FlakyTestList(
        items=[
            FlakyTestItem(
                runner=CITestRunner(runner),
                nodeid=nodeid,
                # Older spans carry no selector, so it is rebuilt from the nodeid.
                selector=selector or selector_from_nodeid(nodeid),
                classification=FlakyTestClassification.from_run_evidence(
                    quarantined_failed_run_count=quarantined_failed_run_count,
                    same_commit_recovery_run_count=same_commit_recovery_run_count,
                ),
                same_commit_recovery_run_count=same_commit_recovery_run_count,
                failed_run_count=failed_run_count,
                failed_pr_count=failed_pr_count,
                master_failed_run_count=master_failed_run_count,
                quarantined_failed_run_count=quarantined_failed_run_count,
                last_signal_at=last_signal_at,
            )
            for (
                runner,
                nodeid,
                selector,
                same_commit_recovery_run_count,
                failed_run_count,
                failed_pr_count,
                master_failed_run_count,
                quarantined_failed_run_count,
                last_signal_at,
            ) in rows[:limit]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )
