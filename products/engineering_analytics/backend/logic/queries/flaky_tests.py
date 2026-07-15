"""Rank active CI test-health recommendations from per-test trace spans.

The emitter records failures, errors, xfails, pass-on-retry outcomes, and ordinary passes above a
duration threshold. The query therefore reports absolute evidence only, never a failure rate.
Rows are deduplicated by pytest nodeid and GitHub run attempt before aggregation.

A test is confirmed flaky only when recorded runs show recovery: pass-on-retry, or ordinary pass and
failure runs interleaved over time. Repeated failures without recovery are suspected regressions.
Xfailed runs are separated as already-quarantined tests. Signals older than three days are omitted
from the active queue even when the requested evidence window is wider.
"""

from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    FlakyTestClassification,
    FlakyTestItem,
    FlakyTestList,
    FlakyTestRecommendation,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_RECORDED_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed", "passed"]
_CI_SERVICE_NAME = "ci-backend"
_ACTIVE_SIGNAL_MAX_AGE = timedelta(days=3)

_SELECT = """
    SELECT
        nodeid,
        selector,
        if(
            quarantined_failed_run_count > 0,
            'quarantined',
            if(has_confirmed_recovery, 'confirmed_flake', 'suspected_regression')
        ) AS classification,
        if(
            classification = 'quarantined',
            'deflake',
            if(
                classification = 'suspected_regression',
                'investigate_regression',
                if(master_failed_run_count > 0 OR affected_run_count >= 3, 'consider_quarantine', 'deflake')
            )
        ) AS recommendation,
        affected_run_count,
        failed_run_count,
        affected_pr_count,
        master_failed_run_count,
        rerun_recovery_run_count,
        recorded_pass_run_count,
        has_interleaved_runs,
        quarantined_failed_run_count,
        last_signal_at,
        last_recorded_execution_at
    FROM (
        SELECT
            nodeid,
            anyIf(selector, selector != '') AS selector,
            countIf(has_failure OR has_rerun_recovery OR has_quarantine_failure) AS affected_run_count,
            countIf(has_failure) AS failed_run_count,
            uniqIf(pr_number, (has_failure OR has_rerun_recovery OR has_quarantine_failure) AND pr_number != '')
                AS affected_pr_count,
            countIf(has_failure AND branch IN ('master', 'main')) AS master_failed_run_count,
            countIf(has_rerun_recovery) AS rerun_recovery_run_count,
            countIf(has_recorded_pass AND NOT has_failure AND NOT has_rerun_recovery AND NOT has_quarantine_failure)
                AS recorded_pass_run_count,
            countIf(has_quarantine_failure) AS quarantined_failed_run_count,
            minIf(run_timestamp, has_failure) AS first_failure_at,
            maxIf(run_timestamp, has_failure) AS last_failure_at,
            minIf(
                run_timestamp,
                has_recorded_pass AND NOT has_failure AND NOT has_rerun_recovery AND NOT has_quarantine_failure
            ) AS first_recorded_pass_at,
            maxIf(
                run_timestamp,
                has_recorded_pass AND NOT has_failure AND NOT has_rerun_recovery AND NOT has_quarantine_failure
            ) AS last_recorded_pass_at,
            maxIf(run_timestamp, has_failure OR has_rerun_recovery OR has_quarantine_failure) AS last_signal_at,
            max(run_timestamp) AS last_recorded_execution_at,
            rerun_recovery_run_count >= {min_rerun_passes}
                OR (
                    failed_run_count > 0
                    AND recorded_pass_run_count > 0
                    AND first_failure_at < last_recorded_pass_at
                    AND first_recorded_pass_at < last_failure_at
                ) AS has_confirmed_recovery,
            failed_run_count > 0
                AND recorded_pass_run_count > 0
                AND first_failure_at < last_recorded_pass_at
                AND first_recorded_pass_at < last_failure_at AS has_interleaved_runs
        FROM (
            SELECT
                nodeid,
                anyIf(selector, selector != '') AS selector,
                anyIf(pr_number, pr_number != '') AS pr_number,
                anyIf(branch, branch != '') AS branch,
                max(outcome IN ('failed', 'error')) AS has_failure,
                max(outcome = 'rerun_passed') AS has_rerun_recovery,
                max(outcome = 'xfailed') AS has_quarantine_failure,
                max(outcome = 'passed') AS has_recorded_pass,
                max(span_timestamp) AS run_timestamp
            FROM (
                SELECT
                    name AS nodeid,
                    attributes['test.selector'] AS selector,
                    attributes['test.outcome'] AS outcome,
                    resource_attributes['ci.pr_number'] AS pr_number,
                    resource_attributes['ci.branch'] AS branch,
                    concat(
                        if(resource_attributes['ci.run_id'] != '', resource_attributes['ci.run_id'], trace_id),
                        ':',
                        if(resource_attributes['ci.run_attempt'] != '', resource_attributes['ci.run_attempt'], '1')
                    ) AS run_attempt_key,
                    timestamp AS span_timestamp
                FROM posthog.trace_spans
                WHERE service_name = {service_name}
                    AND attributes['test.outcome'] IN {recorded_outcomes}
                    AND lower(resource_attributes['ci.repository']) = lower({repository})
                    AND timestamp >= {date_from} __DATE_TO__
            )
            GROUP BY nodeid, run_attempt_key
        )
        GROUP BY nodeid
        HAVING last_signal_at >= {active_after}
            AND (
                quarantined_failed_run_count > 0
                OR has_confirmed_recovery
                OR affected_pr_count >= {min_failed_prs}
                OR master_failed_run_count > 0
            )
            AND NOT (
                rerun_recovery_run_count = 0
                AND NOT has_interleaved_runs
                AND last_recorded_execution_at > last_signal_at
            )
    )
    ORDER BY
        if(last_signal_at >= {recent_after}, 0, 1) ASC,
        multiIf(recommendation = 'investigate_regression', 0, recommendation = 'consider_quarantine', 1, 2) ASC,
        affected_run_count DESC,
        affected_pr_count DESC,
        last_signal_at DESC,
        nodeid ASC
    LIMIT {limit_plus_one}
"""


def _selector_from_nodeid(nodeid: str) -> str:
    """Build a best-effort runnable selector for older spans without ``test.selector``."""
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
    min_rerun_passes: int,
    min_failed_prs: int,
    limit: int,
) -> FlakyTestList:
    repository = curated.repository
    if not repository:
        return FlakyTestList(items=[], truncated=False, limit=limit)

    reference_time = date_to or datetime.now(UTC)
    date_to_clause = "AND timestamp <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=_CI_SERVICE_NAME),
        "recorded_outcomes": ast.Constant(value=_RECORDED_OUTCOMES),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "active_after": ast.Constant(value=reference_time - _ACTIVE_SIGNAL_MAX_AGE),
        "recent_after": ast.Constant(value=reference_time - timedelta(days=1)),
        "min_rerun_passes": ast.Constant(value=min_rerun_passes),
        "min_failed_prs": ast.Constant(value=min_failed_prs),
        "limit_plus_one": ast.Constant(value=limit + 1),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    response = curated.run(
        _SELECT.replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.flaky_tests",
        placeholders=placeholders,
        workload=Workload.LOGS,
    )
    rows = response.results or []
    return FlakyTestList(
        items=[
            FlakyTestItem(
                nodeid=nodeid,
                selector=selector or _selector_from_nodeid(nodeid),
                classification=FlakyTestClassification(classification),
                recommendation=FlakyTestRecommendation(recommendation),
                affected_run_count=affected_run_count,
                failed_run_count=failed_run_count,
                affected_pr_count=affected_pr_count,
                master_failed_run_count=master_failed_run_count,
                rerun_recovery_run_count=rerun_recovery_run_count,
                recorded_pass_run_count=recorded_pass_run_count,
                has_interleaved_runs=has_interleaved_runs,
                quarantined_failed_run_count=quarantined_failed_run_count,
                last_signal_at=last_signal_at,
                last_recorded_execution_at=last_recorded_execution_at,
            )
            for (
                nodeid,
                selector,
                classification,
                recommendation,
                affected_run_count,
                failed_run_count,
                affected_pr_count,
                master_failed_run_count,
                rerun_recovery_run_count,
                recorded_pass_run_count,
                has_interleaved_runs,
                quarantined_failed_run_count,
                last_signal_at,
                last_recorded_execution_at,
            ) in rows[:limit]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )
