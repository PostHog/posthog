"""HogQL aggregation of per-test CI spans into a flaky-test leaderboard.

Backend CI emits one OTel span per test into the Traces store (span name = reconstructed
pytest nodeid, ``test.outcome`` / ``test.attempts`` span attributes, ``ci.*`` resource
attributes — see ``.github/scripts/report_test_timings.py``). This groups the signal spans
by nodeid over a window and ranks tests by flakiness signal.

Two data caveats shape the query:

- Passing tests under the emitter's duration threshold are dropped, while failures, errors,
  xfails, and reruns are always emitted — denominators are biased, so everything here is an
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

# Only test spans carry test.outcome (job-root and setup spans don't), and only these
# outcomes are flaky signal — plain 'passed'/'skipped' spans never reach the aggregation.
_SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Scope the aggregation to the CI test-timing emitter (report_test_timings.py sets this as
# service.name); without it any team span carrying a test.outcome attribute would pollute.
_CI_SERVICE_NAME = "ci-backend"

_SELECT = """
    SELECT
        nodeid,
        anyIf(selector, selector != '') AS selector,
        countIf(outcome = 'rerun_passed') AS rerun_passed_count,
        countIf(outcome IN ('failed', 'error')) AS failed_count,
        uniqIf(pr_number, outcome IN ('failed', 'error') AND pr_number != '') AS failed_pr_count,
        uniqIf(branch, branch != '') AS branch_count,
        countIf(outcome = 'xfailed') AS xfailed_count,
        max(span_timestamp) AS last_seen_at
    FROM (
        SELECT
            name AS nodeid,
            attributes['test.selector'] AS selector,
            attributes['test.outcome'] AS outcome,
            resource_attributes['ci.pr_number'] AS pr_number,
            resource_attributes['ci.branch'] AS branch,
            timestamp AS span_timestamp
        FROM posthog.trace_spans
        WHERE service_name = {service_name}
            AND attributes['test.outcome'] IN {signal_outcomes}
            AND timestamp >= {date_from} __DATE_TO__
    )
    GROUP BY nodeid
    HAVING rerun_passed_count >= {min_rerun_passes} OR failed_pr_count >= {min_failed_prs}
    ORDER BY (rerun_passed_count + failed_pr_count) DESC, failed_count DESC, last_seen_at DESC
    LIMIT {limit_plus_one}
"""


def _selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span the CI reporter emitted before it stamped
    ``test.selector``. The nodeid folds the file/class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'); re-split on the convention that class segments are
    CamelCase and everything before them is the module file. Newer spans skip this — they carry the
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
    min_rerun_passes: int,
    min_failed_prs: int,
    limit: int,
) -> FlakyTestList:
    date_to_clause = "AND timestamp <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=_CI_SERVICE_NAME),
        "signal_outcomes": ast.Constant(value=_SIGNAL_OUTCOMES),
        "date_from": ast.Constant(value=date_from),
        "min_rerun_passes": ast.Constant(value=min_rerun_passes),
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
                rerun_passed_count=rerun_passed_count,
                failed_count=failed_count,
                failed_pr_count=failed_pr_count,
                branch_count=branch_count,
                xfailed_count=xfailed_count,
                last_seen_at=last_seen_at,
            )
            for nodeid, selector, rerun_passed_count, failed_count, failed_pr_count, branch_count, xfailed_count, last_seen_at in rows[
                :limit
            ]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )
