"""Per-test CI spans rolled up by the owning team stamped on each span (``test.owner_team``).

Every figure is an absolute count, never a rate, because passing runs under the emission threshold
have no spans. Spans with no stamp aggregate under the team ``'unowned'``.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    CITestRunner,
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamTestSignal,
)
from products.engineering_analytics.backend.logic._shared import _prior_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    query_setup_breaks,
    run_evidence,
    scan_placeholders,
    selector_from_nodeid,
)

# One scan covers [scan_from, date_to]. `is_current` separates the current window from the prior one.
_RUN_EVIDENCE = run_evidence(bounded=True)

_RUN_IDENTITY = "(ci_engine, workflow_run_key, head_sha, run_id)"

# The latest ownership stamp owns the whole test, so a re-stamped test never counts for two teams.
_ROSTER_SELECT = f"""
    SELECT
        owner_team,
        countIf(notEmpty(recovery_runs_current)) AS flaky_test_count,
        countIf(notEmpty(recovery_runs_prior)) AS flaky_test_count_prior,
        countIf(empty(recovery_runs_current) AND blast_radius_current) AS regression_test_count,
        countIf(empty(recovery_runs_prior) AND blast_radius_prior) AS regression_test_count_prior,
        -- One run can fail many owned tests. The run counts take the union of run ids across the
        -- team's tests, because a sum of per-test run counts counts that run once per test.
        length(groupUniqArrayArray(failed_runs_current)) AS failed_run_count,
        length(groupUniqArrayArray(failed_runs_prior)) AS failed_run_count_prior,
        length(groupUniqArrayArray(recovery_runs_current)) AS same_commit_recovery_run_count,
        length(groupUniqArrayArray(recovery_runs_prior)) AS same_commit_recovery_run_count_prior,
        length(groupUniqArrayArray(xfail_runs_current)) AS quarantined_failed_run_count,
        length(groupUniqArrayArray(xfail_runs_prior)) AS quarantined_failed_run_count_prior,
        max(last_signal) AS last_seen_at
    FROM (
        SELECT
            runner,
            nodeid,
            argMax(owner_team, run_signal_at) AS owner_team,
            groupUniqArrayIf({_RUN_IDENTITY},recovered_in_run AND is_current) AS recovery_runs_current,
            groupUniqArrayIf({_RUN_IDENTITY},recovered_in_run AND NOT is_current) AS recovery_runs_prior,
            groupUniqArrayIf({_RUN_IDENTITY},failed_in_run AND is_current) AS failed_runs_current,
            groupUniqArrayIf({_RUN_IDENTITY},failed_in_run AND NOT is_current) AS failed_runs_prior,
            groupUniqArrayIf({_RUN_IDENTITY},quarantined_in_run AND is_current) AS xfail_runs_current,
            groupUniqArrayIf({_RUN_IDENTITY},quarantined_in_run AND NOT is_current) AS xfail_runs_prior,
            countIf(failed_in_run AND branch IN ('master', 'main') AND is_current) > 0
                OR uniqIf(pr_number, failed_in_run AND pr_number != '' AND is_current) >= {{min_failed_prs}}
                AS blast_radius_current,
            countIf(failed_in_run AND branch IN ('master', 'main') AND NOT is_current) > 0
                OR uniqIf(pr_number, failed_in_run AND pr_number != '' AND NOT is_current) >= {{min_failed_prs}}
                AS blast_radius_prior,
            max(run_signal_at) AS last_signal
        FROM ({_RUN_EVIDENCE})
        GROUP BY runner, nodeid
    )
    GROUP BY owner_team
    __OWNER_FILTER__
    ORDER BY
        (flaky_test_count + regression_test_count) DESC,
        (flaky_test_count_prior + regression_test_count_prior) DESC,
        owner_team ASC
    LIMIT {{limit_plus_one}}
"""

_TEST_SIGNAL_SELECT = f"""
    SELECT
        runner,
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(is_current AND (failed_in_run OR recovered_in_run)) AS signal_count,
        countIf(NOT is_current AND (failed_in_run OR recovered_in_run)) AS signal_count_prior,
        max(run_signal_at) AS last_seen_at
    FROM ({_RUN_EVIDENCE})
    GROUP BY runner, nodeid
    -- Latest stamp owns the whole test, exactly as the roster counts it, so this drill-in never
    -- shows different rows than the summary that opened it.
    HAVING argMax(owner_team, run_signal_at) = {{owner_team}}
        AND (signal_count > 0 OR signal_count_prior > 0)
    ORDER BY greatest(signal_count, signal_count_prior) DESC, signal_count DESC, nodeid ASC, runner ASC
    LIMIT {{test_limit_plus_one}}
"""


def _window_placeholders(
    *, curated: CuratedGitHubSource, date_from: datetime, date_to: datetime | None
) -> dict[str, ast.Expr]:
    window = _prior_window(date_from, date_to)
    return scan_placeholders(
        repository=curated.repository,
        date_from=date_from,
        scan_from=window.scan_from,
        date_to=window.resolved_to,
        setup_breaks=query_setup_breaks(
            curated=curated, date_from=date_from, scan_from=window.scan_from, date_to=window.resolved_to
        ),
    )


def query_team_ci_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_failed_prs: int,
    limit: int,
    owner_team: str | None = None,
) -> TeamCIHealthList:
    # Without a repository identity, another connected repo's spans would leak into this roster.
    if not curated.repository:
        return TeamCIHealthList(items=[], truncated=False, limit=limit)

    placeholders = _window_placeholders(curated=curated, date_from=date_from, date_to=date_to)
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)
    if owner_team is not None:
        placeholders["roster_owner_team"] = ast.Constant(value=owner_team)

    response = curated.run(
        _ROSTER_SELECT.replace(
            "__OWNER_FILTER__", "HAVING owner_team = {roster_owner_team}" if owner_team is not None else ""
        ),
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
                regression_test_count=regression_test_count,
                regression_test_count_prior=regression_test_count_prior,
                failed_run_count=failed_run_count,
                failed_run_count_prior=failed_run_count_prior,
                same_commit_recovery_run_count=same_commit_recovery_run_count,
                same_commit_recovery_run_count_prior=same_commit_recovery_run_count_prior,
                quarantined_failed_run_count=quarantined_failed_run_count,
                quarantined_failed_run_count_prior=quarantined_failed_run_count_prior,
                last_seen_at=last_seen_at,
            )
            for (
                owner_team,
                flaky_test_count,
                flaky_test_count_prior,
                regression_test_count,
                regression_test_count_prior,
                failed_run_count,
                failed_run_count_prior,
                same_commit_recovery_run_count,
                same_commit_recovery_run_count_prior,
                quarantined_failed_run_count,
                quarantined_failed_run_count_prior,
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
                runner=CITestRunner(runner),
                nodeid=nodeid,
                selector=selector or selector_from_nodeid(nodeid),
                signal_count=signal_count,
                signal_count_prior=signal_count_prior,
                last_seen_at=last_seen_at,
            )
            for runner, nodeid, selector, signal_count, signal_count_prior, last_seen_at in test_rows[:test_limit]
        ],
        truncated_tests=len(test_rows) > test_limit,
    )
