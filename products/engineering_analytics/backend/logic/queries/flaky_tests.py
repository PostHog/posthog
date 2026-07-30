"""HogQL aggregation of per-test CI spans into a flaky-test leaderboard.

Embeds the shared per-test span scan (``_test_spans``, the one definition of the service
fence, signal outcomes, and repository scoping) and groups the signal spans by nodeid over
a window, ranking tests by flakiness signal.

Two data caveats shape the query:

- Passing tests under the emitter's duration threshold are dropped, while failures, errors,
  xfails, and reruns are always emitted, so denominators are biased and everything here is an
  absolute count, never a rate.
- ``rerun_passed`` (pass-on-retry, the strongest flaky signal) only flows from lanes running
  pytest with reruns enabled. Lanes without reruns surface a flake as a plain ``failed`` /
  ``error`` span, so the cross-PR failure count is the qualifying signal for those.

Ranking is ``rerun_passed_count + failed_pr_count``: reruns catch the rerun-enabled lanes,
distinct-PRs-hit catches the rest, and neither is inflated by one broken PR failing the same
test on every push (that raises only ``failed_count``, the tiebreaker).

Reads the ``posthog.trace_spans`` table on the LOGS ClickHouse cluster, not the warehouse.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import FlakyTestItem, FlakyTestList
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    flaky_bar,
    scan_placeholders,
    selector_from_nodeid,
    span_scan,
)

_SELECT = f"""
    SELECT
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(outcome = 'rerun_passed') AS rerun_passed_count,
        countIf(outcome IN ('failed', 'error')) AS failed_count,
        uniqIf(pr_number, outcome IN ('failed', 'error') AND pr_number != '') AS failed_pr_count,
        countIf(outcome IN ('failed', 'error') AND branch IN ('master', 'main')) AS master_failed_count,
        uniqIf(branch, branch != '') AS branch_count,
        countIf(outcome = 'xfailed') AS xfailed_count,
        max(span_timestamp) AS last_seen_at
    FROM (__SPAN_SCAN__)
    GROUP BY nodeid
    HAVING {flaky_bar("rerun_passed_count", "failed_pr_count")}
    ORDER BY (rerun_passed_count + failed_pr_count) DESC, failed_count DESC, last_seen_at DESC
    LIMIT {{limit_plus_one}}
"""


def query_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_rerun_passes: int,
    min_failed_prs: int,
    limit: int,
) -> FlakyTestList:
    repository = curated.repository
    # Fail closed: the spans are scoped to the source's repository. Without a repository identity we
    # cannot tell one connected repo's spans from another, so return nothing rather than leak every
    # repository's flaky signals into the selected source's leaderboard.
    if not repository:
        return FlakyTestList(items=[], truncated=False, limit=limit)

    placeholders = scan_placeholders(repository=repository, date_from=date_from, date_to=date_to)
    placeholders["min_rerun_passes"] = ast.Constant(value=min_rerun_passes)
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    # +1 so a full page tells us more tests qualified than returned.
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)

    response = curated.run(
        _SELECT.replace("__SPAN_SCAN__", span_scan(bounded=date_to is not None)),
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
                rerun_passed_count=rerun_passed_count,
                failed_count=failed_count,
                failed_pr_count=failed_pr_count,
                master_failed_count=master_failed_count,
                branch_count=branch_count,
                xfailed_count=xfailed_count,
                last_seen_at=last_seen_at,
            )
            for nodeid, selector, rerun_passed_count, failed_count, failed_pr_count, master_failed_count, branch_count, xfailed_count, last_seen_at in rows[
                :limit
            ]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )
