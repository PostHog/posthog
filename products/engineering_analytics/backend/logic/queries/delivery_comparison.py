"""Curated query: an author's ready-to-merge medians next to their team's and the repository's.

The merged pull requests come from the delivery summary's own read, so all three populations share one
definition with the summary figures. The team population is the team's members' pull requests, which is
what a github_team delivery scope reads too.
"""

from datetime import UTC, datetime, timedelta

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    UNOWNED_TEAM,
    DeliveryComparison,
    DeliveryScopeKind,
    TeamReadyToMergeMedians,
)
from products.engineering_analytics.backend.logic.comparison_teams import TeamChoice, choose_comparison_teams
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    run_started_floor_constant,
)
from products.engineering_analytics.backend.logic.queries.census_counts import query_census_counts
from products.engineering_analytics.backend.logic.queries.delivery_summary import (
    CI_LOOKBACK,
    pull_request_ready_to_merge,
    query_ready_to_merge_facts,
    ready_to_merge_medians,
)

# The census runs daily, so a few days always find its latest run.
_CENSUS_LOOKBACK = timedelta(days=3)

# Every team the author is in, with all of its members.
_AUTHOR_TEAMS_SELECT = f"""
    SELECT team_slug, groupUniqArray(member_handle) AS members
    FROM __MEMBERS_SOURCE__ AS m
    WHERE team_slug IN (
        SELECT team_slug FROM __MEMBERS_SOURCE__ AS mine WHERE mine.member_handle = {{author}}
    )
    GROUP BY team_slug
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

# Per team: the author's pull requests that asked it to review in the window, and whether the pull
# request in focus asked it at any time since the scan floor.
_REQUESTS_SELECT = f"""
    SELECT
        team_slug,
        uniqIf(pr_number, requested_at >= {{date_from}} __REQUESTED_TO__) AS window_prs,
        countIf(pr_number = {{focus_pr}}) AS focus_requests
    FROM __REQUESTS_SOURCE__ AS rr
    WHERE team_slug IN {{teams}}
        AND pr_number IN (SELECT number FROM __PR_SOURCE__ AS pr WHERE pr.author_handle = {{author}})
    GROUP BY team_slug
    LIMIT {UNPAGED_SCAN_LIMIT}
"""


def _query_author_teams(curated: CuratedGitHubSource, *, author: str) -> dict[str, set[str]]:
    members_source = curated.members_source()
    if members_source is None:
        return {}
    response = curated.run(
        _AUTHOR_TEAMS_SELECT.replace("__MEMBERS_SOURCE__", members_source),
        query_type="engineering_analytics.delivery_comparison_teams",
        placeholders={"author": ast.Constant(value=author)},
    )
    return {team: set(members) for team, members in response.results or [] if team}


def _query_code_teams(curated: CuratedGitHubSource) -> set[str]:
    now = datetime.now(tz=UTC)
    census_from = now - _CENSUS_LOOKBACK
    code_teams = set(query_census_counts(curated=curated, date_from=census_from, scan_from=census_from, date_to=now))
    code_teams.discard(UNOWNED_TEAM)
    return code_teams


def _choose_teams(
    curated: CuratedGitHubSource,
    *,
    author: str,
    author_teams: set[str],
    focus_pr: int | None,
    date_from: datetime,
    date_to: datetime | None,
) -> TeamChoice:
    code_teams = _query_code_teams(curated) if author_teams else set()
    requests_source = curated.team_review_requests_source()
    if not author_teams or requests_source is None:
        return choose_comparison_teams(
            author_teams=author_teams, code_teams=code_teams, requested_prs={}, focus_requested=set()
        )
    placeholders: dict[str, ast.Expr] = {
        "author": ast.Constant(value=author),
        "teams": ast.Constant(value=sorted(author_teams)),
        "date_from": ast.Constant(value=date_from),
        # Pull request numbers start at 1, so 0 matches no request.
        "focus_pr": ast.Constant(value=focus_pr or 0),
        "event_created_floor": run_started_floor_constant(date_from - CI_LOOKBACK),
    }
    requested_to = ""
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)
        requested_to = "AND requested_at <= {date_to}"
    response = curated.run(
        _REQUESTS_SELECT.replace("__REQUESTS_SOURCE__", requests_source)
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__REQUESTED_TO__", requested_to),
        query_type="engineering_analytics.delivery_comparison_requests",
        placeholders=placeholders,
    )
    rows = response.results or []
    return choose_comparison_teams(
        author_teams=author_teams,
        code_teams=code_teams,
        requested_prs={team: int(window_prs) for team, window_prs, _focus in rows},
        focus_requested={team for team, _window_prs, focus in rows if focus},
    )


def query_delivery_comparison(
    *,
    curated: CuratedGitHubSource,
    author: str,
    focus_pr: int | None,
    date_from: datetime,
    date_to: datetime | None,
) -> DeliveryComparison:
    author_teams = _query_author_teams(curated, author=author)
    choice = _choose_teams(
        curated,
        author=author,
        author_teams=set(author_teams),
        focus_pr=focus_pr,
        date_from=date_from,
        date_to=date_to,
    )

    scope = DeliveryScope(kind=DeliveryScopeKind.AUTHOR, author=author)
    facts = query_ready_to_merge_facts(curated, scope=scope, date_from=date_from, date_to=date_to)
    focus_fact = next((fact for fact in facts if fact.in_scope and fact.number == focus_pr), None)
    return DeliveryComparison(
        author=author,
        has_membership_data=curated.members_source() is not None,
        review_data_available=curated.reviews_source() is not None,
        ready_data_available=curated.ready_to_merge_sql().observable,
        team_basis=choice.basis,
        author_medians=ready_to_merge_medians([fact for fact in facts if fact.in_scope]),
        teams=[
            TeamReadyToMergeMedians(
                github_team=team,
                medians=ready_to_merge_medians([fact for fact in facts if fact.author in author_teams[team]]),
            )
            for team in choice.teams
        ],
        repo_medians=ready_to_merge_medians(facts),
        pull_request=pull_request_ready_to_merge(focus_fact) if focus_fact else None,
    )
