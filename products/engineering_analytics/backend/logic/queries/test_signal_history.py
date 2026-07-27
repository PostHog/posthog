"""HogQL read of one test's per-run CI signal history: the drill-down behind the test-health queue.

``flaky_tests.py`` aggregates the PR/run dimension away to rank *which* tests are worth acting on;
this keeps that dimension and answers what one test has done across recent runs, PRs, and branches.
Both embed ``_test_spans.run_evidence()``, so the grain (one row per test and CI run) and the meaning
of a recovery are defined once and cannot drift between the queue and its drill-down.

The rollup counts are window aggregates over every matched run, computed in the same pass as the
capped page, so a truncated ``runs`` list never leaves them undercounting against the queue's figures
for the same test and window (SPEC §5).

Reads the ``posthog.trace_spans`` table on the LOGS ClickHouse cluster, not the warehouse.
"""

from datetime import datetime

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    CITestRunner,
    FlakyTestClassification,
    TestSignalHistory,
    TestSignalRun,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import (
    run_evidence,
    scan_placeholders,
    selector_from_nodeid,
)

# The test match sits above run_evidence, not inside its span scan: `selector` only exists once the
# grain rollup has picked the emitted value for the run, so matching any earlier would miss every
# caller who pasted a selector. `OVER ()` runs after the WHERE and before ORDER BY/LIMIT, which is
# what makes the counts window-complete while the page stays capped.
_SELECT = """
    SELECT
        runner,
        nodeid,
        selector,
        run_id,
        pr_number,
        branch,
        failed_in_run,
        recovered_in_run,
        quarantined_in_run,
        run_signal_at,
        countIf(recovered_in_run) OVER () AS same_commit_recovery_run_count,
        countIf(failed_in_run) OVER () AS failed_run_count,
        uniqIf(pr_number, failed_in_run AND pr_number != '') OVER () AS failed_pr_count,
        countIf(failed_in_run AND branch IN ('master', 'main')) OVER () AS master_failed_run_count,
        countIf(quarantined_in_run) OVER () AS quarantined_failed_run_count,
        max(run_signal_at) OVER () AS last_signal_at
    FROM (__RUN_EVIDENCE__)
    WHERE (nodeid = {test} OR selector = {test})__RUNNER_FILTER__
    -- run_id breaks ties so two runs stamped in the same second page deterministically.
    ORDER BY run_signal_at DESC, run_id ASC
    LIMIT {limit_plus_one}
"""


def query_test_signal_history(
    *,
    curated: CuratedGitHubSource,
    test: str,
    runner: CITestRunner | None,
    date_from: datetime,
    date_to: datetime | None,
    limit: int,
) -> TestSignalHistory:
    repository = curated.repository
    # Fail closed: the spans are scoped to the source's repository. Without a repository identity we
    # cannot tell one connected repo's spans from another, so return nothing rather than leak another
    # repository's history for a same-named test.
    if not repository:
        return _empty_history(test=test, limit=limit)

    placeholders = scan_placeholders(repository=repository, date_from=date_from, date_to=date_to)
    placeholders["test"] = ast.Constant(value=test)
    # +1 so a full page tells us more runs matched than returned.
    placeholders["limit_plus_one"] = ast.Constant(value=limit + 1)
    select = _SELECT.replace("__RUN_EVIDENCE__", run_evidence(bounded=date_to is not None))
    if runner is not None:
        placeholders["runner"] = ast.Constant(value=runner.value)
        select = select.replace("__RUNNER_FILTER__", "\n        AND runner = {runner}")
    else:
        select = select.replace("__RUNNER_FILTER__", "")

    response = curated.run(
        select,
        query_type="engineering_analytics.test_signal_history",
        placeholders=placeholders,
        # trace_spans lives on the LOGS ClickHouse cluster, not the warehouse default.
        workload=Workload.LOGS,
    )
    rows = response.results or []
    if not rows:
        return _empty_history(test=test, limit=limit)

    # The window aggregates are identical on every row, so the first row carries the whole rollup
    # alongside the identity the match resolved to.
    (
        matched_runner,
        nodeid,
        selector,
        *_per_run_columns,
        same_commit_recovery_run_count,
        failed_run_count,
        failed_pr_count,
        master_failed_run_count,
        quarantined_failed_run_count,
        last_signal_at,
    ) = rows[0]
    return TestSignalHistory(
        runner=CITestRunner(matched_runner),
        nodeid=nodeid,
        # Prefer the emitter's exact selector; reconstruct from the nodeid for older spans, exactly as
        # the queue does, so both surfaces hand out the same selector for the same test.
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
        runs=[
            TestSignalRun(
                run_id=run_id,
                pr_number=_pr_number(pr_number),
                branch=branch,
                failed=bool(failed_in_run),
                recovered=bool(recovered_in_run),
                quarantined=bool(quarantined_in_run),
                signal_at=run_signal_at,
            )
            for (
                _runner,
                _nodeid,
                _selector,
                run_id,
                pr_number,
                branch,
                failed_in_run,
                recovered_in_run,
                quarantined_in_run,
                run_signal_at,
                *_rollup,
            ) in rows[:limit]
        ],
        truncated=len(rows) > limit,
        limit=limit,
    )


def _empty_history(*, test: str, limit: int) -> TestSignalHistory:
    """No signal in the window: an unknown test is a legitimate empty answer, not a 404."""
    return TestSignalHistory(
        runner=None,
        nodeid=test,
        selector=test,
        classification=None,
        same_commit_recovery_run_count=0,
        failed_run_count=0,
        failed_pr_count=0,
        master_failed_run_count=0,
        quarantined_failed_run_count=0,
        last_signal_at=None,
        runs=[],
        truncated=False,
        limit=limit,
    )


def _pr_number(raw: str) -> int | None:
    # Default-branch pushes carry an empty ci.pr_number stamp, and anything non-numeric is unusable
    # as a PR key, so both read as "no PR association" rather than raising.
    return int(raw) if raw.isdigit() else None
