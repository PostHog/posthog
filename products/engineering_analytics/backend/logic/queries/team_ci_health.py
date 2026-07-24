"""HogQL rollups of per-test CI spans by owning team.

Ownership is stamped on the spans at emission time: the CI reporter resolves each test's
file path with ``OwnersResolver`` over distributed ``owners.yaml`` files (with
``products/*/product.yaml`` aliases) and sets ``test.owner_team``. The server reads a bounded
CI-emitted primary-team catalog instead of duplicating ownership resolution. Spans without a
stamp aggregate under the literal team ``'unowned'``, an honest first-class bucket that surfaces
ownership gaps instead of dropping them.

Teams are organizational owners of code surfaces; nothing here aggregates by author
(SPEC §2). Both queries group ``_test_spans.run_evidence()``, so they carry its caveats and its
grain: sub-threshold passing runs are not emitted, so every figure is an absolute count over
signal spans, never a rate.

This is the ownership dimension of the test-health data: only these spans know which team owns a
test and what its failures cost the fleet.

Reads the ``posthog.trace_spans`` table on the LOGS ClickHouse cluster, not the warehouse.
"""

import json
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamTestSignal,
    TestSurface,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    UNOWNED_TEAM,
    run_evidence,
    scan_placeholders,
    selector_from_nodeid,
)

# The shared run evidence, bounded and scanning [scan_from, date_to] in one pass; `is_current`
# splits the current window from its equal-length prior twin.
_RUN_EVIDENCE = run_evidence(bounded=True)

_OWNERSHIP_CATALOG_SELECT = """
    SELECT attributes['ownership.primary_teams_json'], timestamp
    FROM posthog.trace_spans
    WHERE service_name = 'ci-ownership-catalog'
        AND name = 'ownership.catalog'
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {catalog_from}
    ORDER BY timestamp DESC
    LIMIT 10
"""

# Ownership is capture-time truth. A test re-stamped during the window contributes each run to
# the team stamped on that run instead of moving historical evidence to its newest owner.
_ROSTER_SELECT = f"""
    SELECT
        owner_team,
        countIf(recovery_runs_current > 0) AS flaky_test_count,
        countIf(recovery_runs_prior > 0) AS flaky_test_count_prior,
        countIf(recovery_runs_current = 0 AND blast_radius_current) AS regression_test_count,
        countIf(recovery_runs_prior = 0 AND blast_radius_prior) AS regression_test_count_prior,
        sum(failed_runs_current) AS failed_run_count,
        sum(failed_runs_prior) AS failed_run_count_prior,
        sum(recovery_runs_current) AS same_commit_recovery_run_count,
        sum(recovery_runs_prior) AS same_commit_recovery_run_count_prior,
        sum(xfail_runs_current) AS quarantined_failed_run_count,
        sum(xfail_runs_prior) AS quarantined_failed_run_count_prior,
        max(last_signal) AS last_seen_at
    FROM (
        SELECT
            nodeid,
            surface,
            owner_team,
            countIf(recovered_in_run AND is_current) AS recovery_runs_current,
            countIf(recovered_in_run AND NOT is_current) AS recovery_runs_prior,
            countIf(failed_in_run AND is_current) AS failed_runs_current,
            countIf(failed_in_run AND NOT is_current) AS failed_runs_prior,
            countIf(quarantined_in_run AND is_current) AS xfail_runs_current,
            countIf(quarantined_in_run AND NOT is_current) AS xfail_runs_prior,
            countIf(failed_in_run AND branch IN ('master', 'main') AND is_current) > 0
                OR uniqIf(pr_number, failed_in_run AND pr_number != '' AND is_current) >= {{min_failed_prs}}
                AS blast_radius_current,
            countIf(failed_in_run AND branch IN ('master', 'main') AND NOT is_current) > 0
                OR uniqIf(pr_number, failed_in_run AND pr_number != '' AND NOT is_current) >= {{min_failed_prs}}
                AS blast_radius_prior,
            max(run_signal_at) AS last_signal
        FROM ({_RUN_EVIDENCE})
        GROUP BY nodeid, surface, owner_team
    )
    GROUP BY owner_team
    ORDER BY
        (flaky_test_count + regression_test_count) DESC,
        (flaky_test_count_prior + regression_test_count_prior) DESC,
        owner_team ASC
    LIMIT {{limit_plus_one}}
"""

_TEST_SIGNAL_SELECT = f"""
    SELECT
        nodeid,
        surface,
        anyIf(selector, selector != '') AS selector,
        countIf(is_current AND (failed_in_run OR recovered_in_run)) AS signal_count,
        countIf(NOT is_current AND (failed_in_run OR recovered_in_run)) AS signal_count_prior,
        max(run_signal_at) AS last_seen_at
    FROM ({_RUN_EVIDENCE})
    WHERE owner_team = {{owner_team}}
    GROUP BY nodeid, surface
    HAVING signal_count > 0 OR signal_count_prior > 0
    ORDER BY greatest(signal_count, signal_count_prior) DESC, signal_count DESC, nodeid ASC
    LIMIT {{test_limit_plus_one}}
"""


def _window_placeholders(
    *, curated: CuratedGitHubSource, date_from: datetime, date_to: datetime | None, surface: TestSurface
) -> dict[str, ast.Expr]:
    # The prior window twins the current one: [scan_from, date_from) vs [date_from, date_to].
    resolved_to = date_to or datetime.now(tz=date_from.tzinfo)
    prior_from = date_from - (resolved_to - date_from)
    return scan_placeholders(
        repository=curated.repository,
        date_from=date_from,
        scan_from=prior_from,
        date_to=resolved_to,
        surface=surface,
    )


def _query_ownership_catalog(curated: CuratedGitHubSource) -> tuple[list[str] | None, datetime | None]:
    response = curated.run(
        _OWNERSHIP_CATALOG_SELECT,
        query_type="engineering_analytics.ownership_catalog",
        placeholders={
            "repository": ast.Constant(value=curated.repository),
            "catalog_from": ast.Constant(value=datetime.now(UTC) - timedelta(days=30)),
        },
        workload=Workload.LOGS,
    )
    for raw_teams, captured_at in response.results or []:
        try:
            teams = json.loads(raw_teams)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(teams, list) and all(isinstance(team, str) and team for team in teams):
            primary_teams = {team for team in teams if team != UNOWNED_TEAM and not team.startswith("@")}
            return sorted(primary_teams), captured_at
    return None, None


def _empty_team(owner_team: str) -> TeamCIHealthItem:
    return TeamCIHealthItem(
        owner_team=owner_team,
        has_test_activity=False,
        flaky_test_count=0,
        flaky_test_count_prior=0,
        regression_test_count=0,
        regression_test_count_prior=0,
        failed_run_count=0,
        failed_run_count_prior=0,
        same_commit_recovery_run_count=0,
        same_commit_recovery_run_count_prior=0,
        quarantined_failed_run_count=0,
        quarantined_failed_run_count_prior=0,
        last_seen_at=None,
    )


def query_team_ci_health(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    min_failed_prs: int,
    limit: int,
    surface: TestSurface,
) -> TeamCIHealthList:
    # Fail closed, same as flaky_tests: without a repository identity another connected
    # repo's spans would leak into this roster.
    if not curated.repository:
        return TeamCIHealthList(items=[], truncated=False, limit=limit, surface=surface)

    catalog_teams, catalog_captured_at = _query_ownership_catalog(curated)
    placeholders = _window_placeholders(curated=curated, date_from=date_from, date_to=date_to, surface=surface)
    placeholders["min_failed_prs"] = ast.Constant(value=min_failed_prs)
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)

    response = curated.run(
        _ROSTER_SELECT,
        query_type="engineering_analytics.team_ci_health",
        placeholders=placeholders,
        workload=Workload.LOGS,
    )
    rows = response.results or []
    signal_items = [
        TeamCIHealthItem(
            owner_team=owner_team,
            has_test_activity=True,
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
        ) in rows
    ]
    by_team = {item.owner_team: item for item in signal_items}
    for owner_team in catalog_teams or []:
        by_team.setdefault(owner_team, _empty_team(owner_team))
    items = sorted(
        by_team.values(),
        key=lambda item: (
            not item.has_test_activity,
            -(item.flaky_test_count + item.regression_test_count),
            -(item.flaky_test_count_prior + item.regression_test_count_prior),
            -item.failed_run_count,
            -item.failed_run_count_prior,
            item.owner_team,
        ),
    )
    return TeamCIHealthList(
        items=items[:limit],
        truncated=len(items) > limit,
        limit=limit,
        surface=surface,
        has_ownership_catalog=catalog_teams is not None,
        ownership_catalog_captured_at=catalog_captured_at,
    )


def query_team_ci_activity(
    *,
    curated: CuratedGitHubSource,
    owner_team: str,
    date_from: datetime,
    date_to: datetime | None,
    test_limit: int,
    surface: TestSurface,
) -> TeamCIActivity:
    if not curated.repository:
        return TeamCIActivity(owner_team=owner_team, tests=[], truncated_tests=False, surface=surface)

    placeholders = _window_placeholders(curated=curated, date_from=date_from, date_to=date_to, surface=surface)
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
                surface=TestSurface(surface_value),
                signal_count=signal_count,
                signal_count_prior=signal_count_prior,
                last_seen_at=last_seen_at,
            )
            for nodeid, surface_value, selector, signal_count, signal_count_prior, last_seen_at in test_rows[
                :test_limit
            ]
        ],
        truncated_tests=len(test_rows) > test_limit,
        surface=surface,
    )
