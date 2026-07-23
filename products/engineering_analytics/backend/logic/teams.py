"""Team-level orchestration: CI health rollups, per-team activity, and merge trend."""

from products.engineering_analytics.backend.facade.contracts import TeamCIActivity, TeamCIHealthList, TeamMergeTrend
from products.engineering_analytics.backend.logic._shared import _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.team_ci_health import (
    query_team_ci_activity,
    query_team_ci_health,
)
from products.engineering_analytics.backend.logic.queries.team_merge_trend import query_team_merge_trend
from products.engineering_analytics.backend.logic.suite_health import (
    DEFAULT_FLAKY_MIN_FAILED_PRS,
    DEFAULT_FLAKY_MIN_RERUN_PASSES,
    MAX_FLAKY_WINDOW_DAYS,
)

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
    min_rerun_passes: int | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
) -> TeamCIHealthList:
    parsed_from, parsed_to = _parse_window(
        curated.team, date_from, date_to, default=_DEFAULT_TEAM_WINDOW, max_days=MAX_FLAKY_WINDOW_DAYS
    )
    min_rerun_passes = min_rerun_passes if min_rerun_passes is not None else DEFAULT_FLAKY_MIN_RERUN_PASSES
    min_failed_prs = min_failed_prs if min_failed_prs is not None else DEFAULT_FLAKY_MIN_FAILED_PRS
    # Same explicit-positive-bar rule as the flaky leaderboard: a zero threshold would
    # silently qualify every test with any signal span.
    if min_rerun_passes < 1 or min_failed_prs < 1:
        raise ValueError("min_rerun_passes and min_failed_prs must be at least 1")
    limit = limit if limit is not None else _DEFAULT_TEAM_LIMIT
    if not 1 <= limit <= _MAX_TEAM_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_TEAM_LIMIT}")
    return query_team_ci_health(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        min_rerun_passes=min_rerun_passes,
        min_failed_prs=min_failed_prs,
        limit=limit,
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
