"""Fetch Trunk.io verdicts for one page of test-health items.

One small warehouse read keyed by the page's nodeids, merged in Python by the caller: the
test-health queries scan the Traces store on the LOGS ClickHouse cluster, where warehouse
tables are not readable, so the annotation join cannot happen in their SQL. The page is
bounded (``limit`` rows), so the IN-filtered read stays tiny.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import TrunkIoTestAnnotation, TrunkIoTestStatus
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT
        runner,
        nodeid,
        argMax(trunk_status, trunk_status = 'broken') AS collapsed_status,
        max(trunk_quarantined) AS collapsed_quarantined,
        argMax(trunk_url, trunk_status = 'broken') AS collapsed_url,
        -- Worst variant, not an average: averaging one leg that fails 40% of the time against
        -- healthy legs hides it. max skips NULLs, so the result is NULL only when no variant
        -- has a rate.
        max(trunk_failure_rate_7d) AS collapsed_rate_7d,
        max(trunk_failure_rate_24h) AS collapsed_rate_24h
    FROM __TRUNK_IO_SOURCE__
    WHERE nodeid IN {nodeids}
    GROUP BY runner, nodeid
"""


def fetch_trunk_io_annotations(
    *, curated: CuratedGitHubSource, trunk_io_source: str, nodeids: list[str]
) -> dict[tuple[str, str], TrunkIoTestAnnotation]:
    """Trunk.io's verdict per ``(runner, nodeid)`` for the given tests; missing keys mean
    Trunk.io doesn't currently call that test unhealthy.

    Trunk.io tracks variants (matrix legs) as separate rows, so one nodeid collapses to a
    single verdict: 'broken' outranks 'flaky' because it is the stronger claim, ``quarantined``
    is true when any variant is quarantined, and each rate is its worst variant.
    """
    if not nodeids:
        return {}
    response = curated.run(
        _SELECT.replace("__TRUNK_IO_SOURCE__", trunk_io_source),
        query_type="engineering_analytics.trunk_io_annotations",
        placeholders={"nodeids": ast.Constant(value=nodeids)},
    )
    return {
        (runner, nodeid): TrunkIoTestAnnotation(
            status=TrunkIoTestStatus(status),
            quarantined=bool(quarantined),
            url=url,
            failure_rate_7d=rate_7d,
            failure_rate_24h=rate_24h,
        )
        for runner, nodeid, status, quarantined, url, rate_7d, rate_24h in (response.results or [])
    }
