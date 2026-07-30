"""The one definition of the per-test CI span scan (domain rules defined once, APOSD).

Backend CI emits one OTel span per test into the Traces store (span name = reconstructed
pytest nodeid, ``test.*`` attributes, ``ci.*`` resource attributes; see
``.github/scripts/report_test_timings.py``). Every query over that signal (the flaky-test
leaderboard and the per-team rollups) embeds this scan, so the service fence, the signal
outcomes, the repository scoping, and the ownership fallback cannot drift apart.
"""

from datetime import datetime

from posthog.hogql import ast

# Only test spans carry test.outcome (job-root and setup spans don't), and only these
# outcomes are flaky signal; plain 'passed'/'skipped' spans never reach any aggregation.
SIGNAL_OUTCOMES = ["failed", "error", "rerun_passed", "xfailed"]

# Scope to the CI test-timing emitter (report_test_timings.py sets this as service.name);
# without it any team span carrying a test.outcome attribute would pollute.
CI_SERVICE_NAME = "ci-backend"

# Spans emitted before the owner stamp existed (or from paths with no owner) group here.
UNOWNED_TEAM = "unowned"


def flaky_bar(rerun_count: str, failed_pr_count: str) -> str:
    """The one flaky-test qualification bar (SPEC §5): enough rerun passes OR enough distinct failed PRs."""
    return f"{rerun_count} >= {{min_rerun_passes}} OR {failed_pr_count} >= {{min_failed_prs}}"


# Scans [scan_from, date_to?]; `is_current` splits rows at {date_from} so a caller scanning
# an extra prior window (scan_from < date_from) gets the current/prior split for free. A
# caller without a prior window passes scan_from = date_from and ignores the column.
_SCAN = """
    SELECT
        name AS nodeid,
        attributes['test.selector'] AS selector,
        attributes['test.outcome'] AS outcome,
        coalesce(nullIf(attributes['test.owner_team'], ''), {unowned_team}) AS owner_team,
        resource_attributes['ci.pr_number'] AS pr_number,
        resource_attributes['ci.branch'] AS branch,
        timestamp AS span_timestamp,
        timestamp >= {date_from} AS is_current
    FROM posthog.trace_spans
    WHERE service_name = {service_name}
        AND attributes['test.outcome'] IN {signal_outcomes}
        AND lower(resource_attributes['ci.repository']) = lower({repository})
        AND timestamp >= {scan_from}__DATE_TO__
"""


def span_scan(*, bounded: bool) -> str:
    """The scan SELECT, with or without the upper time bound (some callers scan to now)."""
    return _SCAN.replace("__DATE_TO__", " AND timestamp <= {date_to}" if bounded else "")


def scan_placeholders(
    *,
    repository: str,
    date_from: datetime,
    scan_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, ast.Expr]:
    placeholders: dict[str, ast.Expr] = {
        "service_name": ast.Constant(value=CI_SERVICE_NAME),
        "signal_outcomes": ast.Constant(value=SIGNAL_OUTCOMES),
        "unowned_team": ast.Constant(value=UNOWNED_TEAM),
        "repository": ast.Constant(value=repository),
        "date_from": ast.Constant(value=date_from),
        "scan_from": ast.Constant(value=scan_from if scan_from is not None else date_from),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
    return placeholders


def selector_from_nodeid(nodeid: str) -> str:
    """Best-effort runnable pytest selector for a span the CI reporter emitted before it stamped
    ``test.selector``. The nodeid folds the file/class boundary into '/' and drops '.py'
    ('posthog/api/test/test_x/TestX::test_y'); re-split on the convention that class segments are
    CamelCase and everything before them is the module file. Newer spans skip this: they carry the
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
