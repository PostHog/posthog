from datetime import UTC, datetime

from products.engineering_analytics.backend.facade.contracts import (
    BROKEN_TEST_SPARKLINE_HOURS,
    TRUNK_QUARANTINE_TTL_DAYS,
    BrokenTestsResult,
    CITestRunner,
    FlakyTestList,
    TrunkQuarantineDebt,
)
from products.engineering_analytics.backend.logic._shared import _parse_date, _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.broken_tests import query_broken_tests
from products.engineering_analytics.backend.logic.queries.flaky_tests import query_flaky_tests
from products.engineering_analytics.backend.logic.queries.trunk_quarantine import query_trunk_quarantine_debt

_DEFAULT_FLAKY_WINDOW = "-7d"
# Per-test spans are high-volume, and Traces retention makes older data incomplete.
MAX_FLAKY_WINDOW_DAYS = 30
DEFAULT_FLAKY_MIN_FAILED_PRS = 3
_DEFAULT_FLAKY_LIMIT = 50
_MAX_FLAKY_LIMIT = 200

# Two days covers the classifier's boundaries: a flaky failure needs a span over 24 hours, and
# a novel one was first seen under 24 hours ago.
_BROKEN_TESTS_WINDOW_DAYS = 2
_BROKEN_TESTS_LIMIT = 200


def build_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    runner: CITestRunner | None = None,
    test: str | None = None,
    branch: str | None = None,
    pr_number: int | None = None,
) -> FlakyTestList:
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_FLAKY_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    min_failed_prs = min_failed_prs if min_failed_prs is not None else DEFAULT_FLAKY_MIN_FAILED_PRS
    # A zero threshold would make its HAVING arm always true and qualify every test with any span.
    if min_failed_prs < 1:
        raise ValueError("min_failed_prs must be at least 1")
    limit = limit if limit is not None else _DEFAULT_FLAKY_LIMIT
    if not 1 <= limit <= _MAX_FLAKY_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_FLAKY_LIMIT}")
    return query_flaky_tests(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
        runner=runner,
        test=test,
        branch=branch,
        pr_number=pr_number,
    )


def build_trunk_quarantine(*, curated: CuratedGitHubSource) -> TrunkQuarantineDebt:
    return query_trunk_quarantine_debt(
        curated=curated,
        ttl_days=TRUNK_QUARANTINE_TTL_DAYS,
        now=datetime.now(UTC),
    )


def build_broken_tests(
    *, curated: CuratedGitHubSource, test: str | None = None, branch: str | None = None
) -> BrokenTestsResult:
    # The SQL uses now() for the age and span math, so these bounds only floor the scans.
    return query_broken_tests(
        curated=curated,
        date_from=_parse_date(curated.team, f"-{_BROKEN_TESTS_WINDOW_DAYS}d"),
        hourly_from=_parse_date(curated.team, f"-{BROKEN_TEST_SPARKLINE_HOURS}h"),
        window_days=_BROKEN_TESTS_WINDOW_DAYS,
        limit=_BROKEN_TESTS_LIMIT,
        test=test,
        branch=branch,
    )
