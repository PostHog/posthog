"""Team-level orchestration: CI health rollups, per-team activity, and merge trend."""

from dataclasses import replace
from datetime import datetime

from products.engineering_analytics.backend.facade.contracts import (
    TeamCIActivity,
    TeamCIHealthItem,
    TeamCIHealthList,
    TeamMergeTrend,
)
from products.engineering_analytics.backend.logic._shared import _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
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

_UNOWNED_TEAM = "unowned"

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
    )
    return _enrich_roster(roster, curated=curated, date_from=parsed_from, date_to=parsed_to, limit=limit)


def _enrich_roster(
    roster: TeamCIHealthList,
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    limit: int,
) -> TeamCIHealthList:
    """Attach census and merged-PR context, and add census-only rows so a team whose tests
    all pass still appears in the roster instead of vanishing with the signal."""
    resolved_to = date_to or datetime.now(tz=date_from.tzinfo)
    scan_from = date_from - (resolved_to - date_from)
    census = query_census_counts(curated=curated, date_from=date_from, scan_from=scan_from, date_to=resolved_to)
    merged = query_team_merged_pr_counts(curated=curated, date_from=date_from, scan_from=scan_from, date_to=resolved_to)

    def merged_counts(owner_team: str) -> tuple[int | None, int | None]:
        # 'unowned' is not a GitHub team, so a zero would be a made-up number for it.
        if merged is None or owner_team == _UNOWNED_TEAM:
            return None, None
        return merged.get(owner_team, (0, 0))

    def enrich(item: TeamCIHealthItem) -> TeamCIHealthItem:
        test_file_count, test_file_count_prior = census.get(item.owner_team, (None, None))
        merged_pr_count, merged_pr_count_prior = merged_counts(item.owner_team)
        return replace(
            item,
            test_file_count=test_file_count,
            test_file_count_prior=test_file_count_prior,
            merged_pr_count=merged_pr_count,
            merged_pr_count_prior=merged_pr_count_prior,
        )

    signal_slugs = {item.owner_team for item in roster.items}
    quiet_rows = [
        _quiet_row(slug, counts, merged_counts(slug))
        for slug, counts in sorted(census.items(), key=lambda kv: (-(kv[1][0] or 0), kv[0]))
        if slug not in signal_slugs
    ]
    items = [enrich(item) for item in roster.items] + quiet_rows
    return TeamCIHealthList(
        items=items[:limit],
        truncated=roster.truncated or len(items) > limit,
        limit=limit,
    )


def _quiet_row(
    owner_team: str, census_counts: tuple[int | None, int | None], merged_pr_counts: tuple[int | None, int | None]
) -> TeamCIHealthItem:
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
        test_file_count=census_counts[0],
        test_file_count_prior=census_counts[1],
        merged_pr_count=merged_pr_counts[0],
        merged_pr_count_prior=merged_pr_counts[1],
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
