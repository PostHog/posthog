"""HogQL rollups of per-test CI spans by owning team.

Ownership is stamped on the spans at emission time: the CI reporter resolves each test's
file path against the repo's ownership map (``products/*/product.yaml`` + CODEOWNERS) and
sets ``test.owner_team``, so no server-side ownership map exists. Spans without a stamp
aggregate under the literal team ``'unowned'``, an honest first-class bucket that surfaces
ownership gaps instead of dropping them.

Teams are organizational owners of code surfaces; nothing here aggregates by author
(SPEC §2). Both queries share the flaky-tests caveats: sub-threshold passing runs are not
emitted, so every figure is an absolute count over signal spans, never a rate.

Reads the ``posthog.trace_spans`` table on the LOGS ClickHouse cluster, not the warehouse.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamTestSignal,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    flaky_bar,
    scan_placeholders,
    selector_from_nodeid,
    span_scan,
)

# The shared span scan, bounded and scanning [scan_from, date_to] in one pass; `is_current`
# splits the current window from its equal-length prior twin.
_SPAN_SCAN = span_scan(bounded=True)

_ROSTER_SELECT = f"""
    SELECT
        owner_team,
        countIf({flaky_bar("rerun_current", "failed_prs_current")}) AS flaky_test_count,
        countIf({flaky_bar("rerun_prior", "failed_prs_prior")}) AS flaky_test_count_prior,
        sum(failed_current) AS failed_count,
        sum(failed_prior) AS failed_count_prior,
        sum(rerun_current) AS rerun_passed_count,
        sum(rerun_prior) AS rerun_passed_count_prior,
        sum(xfail_current) AS xfailed_count,
        sum(xfail_prior) AS xfailed_count_prior,
        max(last_seen) AS last_seen_at
    FROM (
        SELECT
            owner_team,
            nodeid,
            countIf(outcome = 'rerun_passed' AND is_current) AS rerun_current,
            countIf(outcome = 'rerun_passed' AND NOT is_current) AS rerun_prior,
            countIf(outcome IN ('failed', 'error') AND is_current) AS failed_current,
            countIf(outcome IN ('failed', 'error') AND NOT is_current) AS failed_prior,
            countIf(outcome = 'xfailed' AND is_current) AS xfail_current,
            countIf(outcome = 'xfailed' AND NOT is_current) AS xfail_prior,
            uniqIf(pr_number, outcome IN ('failed', 'error') AND pr_number != '' AND is_current) AS failed_prs_current,
            uniqIf(pr_number, outcome IN ('failed', 'error') AND pr_number != '' AND NOT is_current) AS failed_prs_prior,
            max(span_timestamp) AS last_seen
        FROM ({_SPAN_SCAN})
        GROUP BY owner_team, nodeid
    )
    GROUP BY owner_team
    ORDER BY (flaky_test_count + failed_count) DESC, (flaky_test_count_prior + failed_count_prior) DESC, owner_team ASC
    LIMIT {{limit_plus_one}}
"""

_TEST_SIGNAL_SELECT = f"""
    SELECT
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(is_current AND outcome != 'xfailed') AS signal_count,
        countIf(NOT is_current AND outcome != 'xfailed') AS signal_count_prior,
        max(span_timestamp) AS last_seen_at
    FROM ({_SPAN_SCAN})
    WHERE owner_team = {{owner_team}}
    GROUP BY nodeid
    HAVING signal_count > 0 OR signal_count_prior > 0
    ORDER BY greatest(signal_count, signal_count_prior) DESC, signal_count DESC, nodeid ASC
    LIMIT {{test_limit_plus_one}}
"""


def _window_placeholders(
    *, curated: CuratedGitHubSource, date_from: datetime, date_to: datetime | None
) -> dict[str, ast.Expr]:
    # The prior window twins the current one: [scan_from, date_from) vs [date_from, date_to].
    resolved_to = date_to or datetime.now(tz=date_from.tzinfo)
    prior_from = date_from - (resolved_to - date_from)
    return scan_placeholders(
        repository=curated.repository, date_from=date_from, scan_from=prior_from, date_to=resolved_to
    )


def query_team_ci_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_rerun_passes: int,
    min_failed_prs: int,
    limit: int,
) -> TeamCIHealthList:
    # Fail closed, same as flaky_tests: without a repository identity another connected
    # repo's spans would leak into this roster.
    if not curated.repository:
        return TeamCIHealthList(items=[], truncated=False, limit=limit)

    placeholders = _window_placeholders(curated=curated, date_from=date_from, date_to=date_to)
    placeholders["min_rerun_passes"] = ast.Constant(value=min_rerun_passes)
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)

    response = curated.run(
        _ROSTER_SELECT,
        query_type="engineering_analytics.team_ci_health",
        placeholders=placeholders,
        workload=Workload.LOGS,
    )
    rows = response.results or []
    return TeamCIHealthList(
        items=[
            TeamCIHealthItem(
                owner_team=owner_team,
                flaky_test_count=flaky_test_count,
                flaky_test_count_prior=flaky_test_count_prior,
                failed_count=failed_count,
                failed_count_prior=failed_count_prior,
                rerun_passed_count=rerun_passed_count,
                rerun_passed_count_prior=rerun_passed_count_prior,
                xfailed_count=xfailed_count,
                xfailed_count_prior=xfailed_count_prior,
                last_seen_at=last_seen_at,
            )
            for (
                owner_team,
                flaky_test_count,
                flaky_test_count_prior,
                failed_count,
                failed_count_prior,
                rerun_passed_count,
                rerun_passed_count_prior,
                xfailed_count,
                xfailed_count_prior,
                last_seen_at,
            ) in rows[:limit]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )


def query_team_ci_activity(
    *,
    curated: CuratedGitHubSource,
    owner_team: str,
    date_from: datetime,
    date_to: datetime | None,
    test_limit: int,
) -> TeamCIActivity:
    if not curated.repository:
        return TeamCIActivity(owner_team=owner_team, tests=[], truncated_tests=False)

    placeholders = _window_placeholders(curated=curated, date_from=date_from, date_to=date_to)
    placeholders["owner_team"] = ast.Constant(value=owner_team)

    tests_response = curated.run(
        _TEST_SIGNAL_SELECT,
        query_type="engineering_analytics.team_ci_activity_tests",
        placeholders={**placeholders, "test_limit_plus_one": ast.Constant(value=test_limit + 1)},
        workload=Workload.LOGS,
    )
    test_rows = tests_response.results or []
    return TeamCIActivity(
        owner_team=owner_team,
        tests=[
            TeamTestSignal(
                nodeid=nodeid,
                selector=selector or selector_from_nodeid(nodeid),
                signal_count=signal_count,
                signal_count_prior=signal_count_prior,
                last_seen_at=last_seen_at,
            )
            for nodeid, selector, signal_count, signal_count_prior, last_seen_at in test_rows[:test_limit]
        ],
        truncated_tests=len(test_rows) > test_limit,
    )
