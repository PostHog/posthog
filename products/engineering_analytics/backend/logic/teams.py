"""Team-level orchestration: CI health rollups, per-team activity, and merge trend."""

from dataclasses import replace
from datetime import datetime, timedelta

from products.engineering_analytics.backend.facade.contracts import (
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamMergeTrend,
)
from products.engineering_analytics.backend.logic._shared import WindowedCount, _parse_window, _prior_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._test_spans import UNOWNED_TEAM
from products.engineering_analytics.backend.logic.queries.census_counts import query_census_counts
from products.engineering_analytics.backend.logic.queries.team_ci_health import (
    query_team_ci_activity,
    query_team_ci_health,
)
from products.engineering_analytics.backend.logic.queries.team_merge_trend import query_team_merge_trend
from products.engineering_analytics.backend.logic.queries.team_merged_prs import query_team_merged_pr_counts
from products.engineering_analytics.backend.logic.suite_health import (
    DEFAULT_FLAKY_MIN_FAILED_PRS,
    MAX_FLAKY_WINDOW_DAYS,
)

# The census emits one value per team per day, so a few days of lookback always finds the
# value standing at the window start; scanning the full prior twin would read days of
# events only to discard them.
_CENSUS_LOOKBACK = timedelta(days=3)

# Team CI health rollups scan the current window plus an equal-length prior twin, so the
# default sits below the flaky ceiling to keep both windows inside Traces retention. At the
# 30d cap the prior twin reaches past retention and *_prior counts read low.
_DEFAULT_TEAM_WINDOW = "-14d"
_DEFAULT_TEAM_LIMIT = 100
_MAX_TEAM_LIMIT = 200
_DEFAULT_TEAM_TEST_LIMIT = 25
_MAX_TEAM_TEST_LIMIT = 100


def build_team_ci_health(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    owner_team: str | None = None,
) -> TeamCIHealthList:
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_TEAM_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    min_failed_prs = min_failed_prs if min_failed_prs is not None else DEFAULT_FLAKY_MIN_FAILED_PRS
    # Same explicit-positive-bar rule as the test-health queue: a zero threshold would
    # silently qualify every test with any failure.
    if min_failed_prs < 1:
        raise ValueError("min_failed_prs must be at least 1")
    limit = limit if limit is not None else _DEFAULT_TEAM_LIMIT
    if not 1 <= limit <= _MAX_TEAM_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_TEAM_LIMIT}")
    roster = query_team_ci_health(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
        owner_team=owner_team,
    )
    return _enrich_roster(
        roster, curated=curated, date_from=parsed_from, date_to=parsed_to, limit=limit, owner_team=owner_team
    )


def _enrich_roster(
    roster: TeamCIHealthList,
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    limit: int,
    owner_team: str | None,
) -> TeamCIHealthList:
    """Attach census and merged-PR context, and add census-only rows so a team whose tests
    all pass still appears in the roster instead of vanishing with the signal."""
    window = _prior_window(date_from, date_to)
    census = query_census_counts(
        curated=curated, date_from=date_from, scan_from=date_from - _CENSUS_LOOKBACK, date_to=window.resolved_to
    )
    merged = query_team_merged_pr_counts(
        curated=curated, date_from=date_from, scan_from=window.scan_from, date_to=window.resolved_to
    )
    _NO_COUNTS = WindowedCount(current=None, prior=None)
    _ZERO_COUNTS = WindowedCount(current=0, prior=0)

    def enrich(item: TeamCIHealthItem) -> TeamCIHealthItem:
        # 'unowned' is not a GitHub team, so a zero merged-PR count would be a made-up number.
        merged_counts = (
            merged.get(item.owner_team, _ZERO_COUNTS)
            if merged is not None and item.owner_team != UNOWNED_TEAM
            else _NO_COUNTS
        )
        census_counts = census.get(item.owner_team, _NO_COUNTS)
        return replace(
            item,
            test_file_count=census_counts.current,
            test_file_count_prior=census_counts.prior,
            merged_pr_count=merged_counts.current,
            merged_pr_count_prior=merged_counts.prior,
        )

    signal_slugs = {item.owner_team for item in roster.items}
    quiet_slugs = [
        slug
        for slug, _counts in sorted(census.items(), key=lambda kv: (-(kv[1].current or 0), kv[0]))
        if slug not in signal_slugs and (owner_team is None or slug == owner_team)
    ]
    items = [enrich(item) for item in roster.items] + [enrich(_zero_row(slug)) for slug in quiet_slugs]
    return TeamCIHealthList(
        items=items[:limit],
        truncated=roster.truncated or len(items) > limit,
        limit=limit,
    )


def _zero_row(owner_team: str) -> TeamCIHealthItem:
    return TeamCIHealthItem(
        owner_team=owner_team,
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


def build_team_ci_activity(
    *,
    curated: CuratedGitHubSource,
    owner_team: str,
    date_from: str | None = None,
    date_to: str | None = None,
    test_limit: int | None = None,
) -> TeamCIActivity:
    normalized_team = owner_team.strip()
    if not normalized_team:
        raise ValueError("owner_team is required")
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_TEAM_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    test_limit = test_limit if test_limit is not None else _DEFAULT_TEAM_TEST_LIMIT
    if not 1 <= test_limit <= _MAX_TEAM_TEST_LIMIT:
        raise ValueError(f"test_limit must be between 1 and {_MAX_TEAM_TEST_LIMIT}")
    return query_team_ci_activity(
        curated=curated,
        owner_team=normalized_team,
        date_from=parsed_from,
        date_to=parsed_to,
        test_limit=test_limit,
    )


def build_team_merge_trend(
    *,
    curated: CuratedGitHubSource,
    owner_team: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> TeamMergeTrend:
    normalized_team = owner_team.strip()
    if not normalized_team:
        raise ValueError("owner_team is required")
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_TEAM_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    return query_team_merge_trend(
        curated=curated,
        owner_team=normalized_team,
        date_from=parsed_from,
        date_to=parsed_to,
    )
