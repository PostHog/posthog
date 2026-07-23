"""Test-health orchestration for recent test signals and the broken-tests panel."""

from products.engineering_analytics.backend.facade.contracts import (
    BROKEN_TEST_SPARKLINE_HOURS,
    BrokenTestsResult,
    FlakyTestList,
    TestSurface,
)
from products.engineering_analytics.backend.logic._shared import _parse_date, _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.broken_tests import query_broken_tests
from products.engineering_analytics.backend.logic.queries.flaky_tests import query_flaky_tests

# Test-health queue defaults: a week of signal is the triage window, a month the ceiling
# (per-test spans are high-volume and the short Traces retention makes older data spotty anyway).
# The signal threshold doubles as the bar for the team CI health rollups.
_DEFAULT_FLAKY_WINDOW = "-7d"
MAX_FLAKY_WINDOW_DAYS = 30
DEFAULT_FLAKY_MIN_FAILED_PRS = 3
_DEFAULT_FLAKY_LIMIT = 50
_MAX_FLAKY_LIMIT = 200

# Broken-tests panel: a fixed short window (not caller-tunable in v1, like current_branch_health).
# Two days keeps the logs-cluster scan light while still spanning the classifier's boundaries — a
# flaky failure needs a >24h span and a novel one needs first-seen <24h, both fitting inside 48h.
_BROKEN_TESTS_WINDOW_DAYS = 2
_BROKEN_TESTS_LIMIT = 200


def build_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    surface: str | None = None,
) -> FlakyTestList:
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_FLAKY_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    min_failed_prs = min_failed_prs if min_failed_prs is not None else DEFAULT_FLAKY_MIN_FAILED_PRS
    # A zero threshold would make its HAVING arm trivially true and silently qualify every
    # test with any signal span, so require an explicit positive bar instead.
    if min_failed_prs < 1:
        raise ValueError("min_failed_prs must be at least 1")
    limit = limit if limit is not None else _DEFAULT_FLAKY_LIMIT
    if not 1 <= limit <= _MAX_FLAKY_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_FLAKY_LIMIT}")
    try:
        test_surface = TestSurface(surface or TestSurface.ALL)
    except ValueError as exc:
        raise ValueError("surface must be one of: all, backend, frontend") from exc
    return query_flaky_tests(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
        surface=test_surface,
    )


def build_broken_tests(*, curated: CuratedGitHubSource) -> BrokenTestsResult:
    # Fixed windows resolved through the module's relative-date entry point (like current_branch_health):
    # the 2-day analysis window and the 24h sparkline window. The SQL uses now() for the age/span/offset
    # math, so these bounds only floor the scans.
    return query_broken_tests(
        curated=curated,
        date_from=_parse_date(curated.team, f"-{_BROKEN_TESTS_WINDOW_DAYS}d"),
        hourly_from=_parse_date(curated.team, f"-{BROKEN_TEST_SPARKLINE_HOURS}h"),
        window_days=_BROKEN_TESTS_WINDOW_DAYS,
        limit=_BROKEN_TESTS_LIMIT,
    )
